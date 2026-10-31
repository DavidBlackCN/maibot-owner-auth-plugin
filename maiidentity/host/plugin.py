from __future__ import annotations

from pathlib import Path
import asyncio
from ..runtime_versions import runtime_supported
import secrets
import uuid

from maibot_sdk import API, Command, HookHandler, MaiBotPlugin
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder

from .. import OLD_PLUGIN_ID, PLUGIN_VERSION
from ..context.projection import Projector, snapshot, match_person
from ..identity.messages import MessageResolver, host_message
from ..identity.service import BindingChallenges, IdentityService
from ..integrations.api import PublicAPI, descriptor
from ..policy.service import PolicyService
from ..relations.service import Relations
from ..shared.core import AccountKey, Scope, digest, qq, require
from ..storage.database import Database, WriterLease
from .config import MaiIdentityConfig


async def owned_io(function, *args, **kwargs):
    """Join worker I/O before cancellation cleanup releases its resources."""
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        await work
        raise


class MaiIdentityPlugin(MaiBotPlugin):
    config_model = MaiIdentityConfig

    @classmethod
    def build_config_schema(cls, **metadata):
        from .schema import build_schema
        return build_schema(**metadata)

    def __init__(self):
        super().__init__()
        self.db = self.lease = self.active = self.identity = self.policy = self.relations = None
        self.resolver = self.projector = self.challenges = None
        self.data_lease = None
        self.loaded_config = None
        self.ready = False

    def normalize_plugin_config(self, config_data):
        # Validate raw input before SDK normalization can discard old sections.
        MaiIdentityConfig.model_validate(config_data or {})
        return super().normalize_plugin_config(config_data)

    async def on_load(self):
        require(self.db is None and self.lease is None, "ALREADY_LOADED")
        cfg = self.config
        if not cfg.plugin.enabled:
            return
        try:
            require(runtime_supported(), "UNSUPPORTED_VERSION")
            loaded = await self.ctx.component.list_loaded_plugins()
            require(type(loaded) is list, "REGISTRY_UNAVAILABLE")
            for item in loaded:
                identity = item if type(item) is str else (item.get("plugin_id") or item.get("id") or item.get("name")) if type(item) is dict else None
                require(type(identity) is str and identity != OLD_PLUGIN_ID, "OLD_PLUGIN_ACTIVE")
            data = self.ctx.paths.data_dir
            require(isinstance(data, Path) and data.is_absolute(), "INVALID_DATA_ROOT")
            source = Path(__file__).resolve().parents[2]
            require(data.resolve() != source and source not in data.resolve().parents, "SOURCE_DATA_FORBIDDEN")
            self.lease = WriterLease(Path(cfg.plugin.writer_lock) if cfg.plugin.writer_lock else data/"deployment-writer.lock")
            await owned_io(self.lease.acquire)
            data.mkdir(parents=True, exist_ok=True)
            self.data_lease = WriterLease(data/"writer.lock")
            await owned_io(self.data_lease.acquire)
            from ..storage.activation import validate_activation
            await asyncio.to_thread(validate_activation, data, cfg.model_dump())
            path = data / "identity.db"
            # Assign inside the joined worker so cancellation cannot discard an
            # opened connection before the failure cleanup can see it.
            def open_database():
                self.db = Database(path, create=not path.exists())
            await owned_io(open_database)
            self.loaded_config = cfg.model_copy(deep=True)
            self.active = cfg.model_copy(deep=True)
            # Generated once under the SDK data lock, never inferred from a chat.
            if not self.active.plugin.instance_id:
                self.active.plugin.instance_id = await owned_io(self._instance_id)
            self.identity = IdentityService(self.db)
            self.policy = PolicyService(self.identity)
            self.relations = Relations(self.policy)
            self.challenges = BindingChallenges(self.identity)
            await owned_io(self._bootstrap)
            await owned_io(self._bootstrap_life_management)
            self.resolver = MessageResolver(ttl=cfg.context.cache_ttl_seconds)
            ownership_key = await owned_io(self._context_ownership_key)
            self.projector = Projector(cfg.context.budget_bytes, ownership_key=ownership_key)
            self.ready = True
        except BaseException:
            await self.on_unload()
            raise

    def _instance_id(self):
        from ..shared.core import opaque
        with self.db.transaction():
            row = self.db.conn.execute("SELECT value FROM metadata WHERE key='deployment_instance_id'").fetchone()
            if row is None:
                value = "maiidentity-" + uuid.uuid4().hex
                self.db.conn.execute("INSERT INTO metadata VALUES('deployment_instance_id',?)", (value,))
            else:
                value = row[0]
            return opaque(value)

    def _context_ownership_key(self):
        # Persistent block ownership is NOT an identity/authorization key. It
        # only permits removal of this instance's earlier context after reload.
        with self.db.transaction():
            row = self.db.conn.execute("SELECT value FROM metadata WHERE key='context_ownership_key'").fetchone()
            if row is None:
                value = secrets.token_hex(32)
                self.db.conn.execute("INSERT INTO metadata VALUES('context_ownership_key',?)", (value,))
            else:
                value = row[0]
            key = bytes.fromhex(value)
            require(len(key) == 32, "STORAGE_UNAVAILABLE")
            return key

    def _bootstrap(self):
        cfg = self.active
        accounts = {AccountKey(e.platform, e.adapter_namespace, e.account_id).key for e in cfg.identity.accounts if e.enabled}
        accounts.update(AccountKey('qq',cfg.identity.adapter_namespace,a).key for a in cfg.management.vita_admin_accounts)
        for role in cfg.roles.entries:
            require(AccountKey(role.account.platform, role.account.adapter_namespace, role.account.account_id).key in accounts,
                    "ROLE_ACCOUNT_NOT_CONFIGURED")
        bootstrap_config={"accounts": [e.model_dump() for e in cfg.identity.accounts],
                          "roles": [e.model_dump() for e in cfg.roles.entries]}
        # Preserve the previous fingerprint when the new option is untouched;
        # an upgrade alone must not look like an operator's binding review.
        if cfg.management.vita_admin_accounts: bootstrap_config['management']=cfg.management.model_dump()
        config_hash=digest(bootstrap_config)
        with self.db.transaction():
            old = self.db.get("bootstrap", "current")
            if old and old["hash"] == config_hash:
                return
            for binding in self.db.conn.execute("SELECT * FROM bindings WHERE method='operator_config'").fetchall():
                if binding["account"] not in accounts and binding["status"] == "active":
                    self.db.conn.execute("UPDATE bindings SET status='revoked',epoch=epoch+1 WHERE account=?", (binding["account"],))
                    self.policy._bump(binding["subject"])
            for role in self.db.records("role"):
                if role.get("config_origin") and role["status"] == "active":
                    role["status"] = "revoked"
                    self.db.put("role", role["id"], role, role["revision"])
                    self.policy._bump(role["subject"])
            for grant in self.db.records('grant'):
                if grant.get('management_config_origin') and grant['status']=='active':
                    grant['status']='revoked'
                    self.db.put('grant',grant['id'],grant,grant['revision'])
                    self.policy._bump(grant['subject'])
            for account in sorted(accounts):
                existing = self.db.conn.execute("SELECT * FROM bindings WHERE account=?", (account,)).fetchone()
                if existing:
                    # A revoked binding never reactivates just by reloading the
                    # same config. Changed config is an explicit local review.
                    self.db.conn.execute("UPDATE bindings SET status='active',epoch=epoch+? WHERE account=?",
                                         (int(existing["status"] != "active"), account))
                else:
                    sid = uuid.uuid4().hex
                    self.db.conn.execute("INSERT INTO subjects VALUES(?,'active',1)", (sid,))
                    self.db.conn.execute("INSERT INTO bindings VALUES(?,?,'active',1,'operator_config')", (account, sid))
            for entry in cfg.roles.entries:
                account = AccountKey(entry.account.platform, entry.account.adapter_namespace, entry.account.account_id)
                binding = self.identity.lookup(account)
                ref = uuid.uuid4().hex
                self.db.put("role", ref, {"id": ref, "subject": binding["subject"], "role": entry.role,
                    "scope": entry.scope, "status": "active", "config_origin": True})
                self.policy._bump(binding["subject"])
            for account in cfg.management.vita_admin_accounts:
                binding=self.identity.lookup(AccountKey('qq',cfg.identity.adapter_namespace,account))
                scope=Scope('instance',cfg.plugin.instance_id,'default','qq',cfg.identity.adapter_namespace,'life','default')
                for capability in ('maivita.wake','maivita.replan','maivita.life.manage'):
                    ref=uuid.uuid4().hex
                    self.db.put('grant',ref,{'id':ref,'subject':binding['subject'],'capability':capability,
                        'scope':scope.data(),'effect':'allow','delegable':False,'expires':None,'status':'active',
                        'source':'operator_config','management_config_origin':True})
                self.policy._bump(binding['subject'])
            self.db.put("bootstrap", "current", {"hash": config_hash}, old["revision"] if old else None)
            self.db.audit("bootstrap.reviewed", "current", {"revision": old["revision"]+1 if old else 1})

    def _bootstrap_life_management(self):
        # Add a precise product capability once. Never reactivate revoked
        # accounts or an explicitly revoked grant on an ordinary upgrade.
        cfg=self.active
        with self.db.transaction():
            for account in cfg.management.vita_admin_accounts:
                binding=self.identity.lookup(AccountKey('qq',cfg.identity.adapter_namespace,account))
                if binding is None:continue
                if any(g.get('management_config_origin') and g['subject']==binding['subject']
                       and g['capability']=='maivita.life.manage' for g in self.db.records('grant')):continue
                scope=Scope('instance',cfg.plugin.instance_id,'default','qq',cfg.identity.adapter_namespace,'life','default')
                ref=uuid.uuid4().hex
                self.db.put('grant',ref,{'id':ref,'subject':binding['subject'],'capability':'maivita.life.manage',
                    'scope':scope.data(),'effect':'allow','delegable':False,'expires':None,'status':'active',
                    'source':'operator_config','management_config_origin':True})
                self.policy._bump(binding['subject'])
                self.db.audit('management.product_capability',ref,{'capability':'maivita.life.manage'})

    async def on_unload(self):
        self.ready = False
        try:
            if self.resolver:
                self.resolver.close()
            if self.projector:
                self.projector.close()
            if self.challenges and self.db and self.db.conn is not None:
                await asyncio.to_thread(self.challenges.close)
        finally:
            try:
                if self.db:
                    await owned_io(self.db.close)
            finally:
                if self.data_lease:
                    self.data_lease.release()
                    self.data_lease = None
                self.loaded_config = None
                if self.lease:
                    self.lease.release()
                self.db = self.lease = self.active = self.identity = self.policy = self.relations = None
                self.resolver = self.projector = self.challenges = None

    async def on_config_update(self, scope, config_data, version):
        if scope != "self":
            return
        try:
            new = MaiIdentityConfig.model_validate(config_data)
        except BaseException:
            await self.on_unload()
            raise
        if self.active is not None and new != self.loaded_config:
            if new.model_dump(exclude={'identity': {'people'}}) == self.loaded_config.model_dump(exclude={'identity': {'people'}}):
                # Replace the reading view atomically. In-flight lookups discard old views.
                self.active = self.active.model_copy(update={'identity': new.identity.model_copy(deep=True)})
                self.loaded_config = new.model_copy(deep=True)
                return
            await self.on_unload()
            raise RuntimeError("RELOAD_REQUIRED")

    def _parse(self, raw):
        # Only official Host receive/query/Command serializers reach here.
        # The adapter's route account takes precedence over the global fallback.
        bot = qq(raw.get('account_id')) if type(raw) is dict else ''
        return host_message(raw, instance=self.active.plugin.instance_id,
                            namespace=self.active.identity.adapter_namespace, bot_account=bot,
                            route_scope=self.active.identity.route_scope)

    @HookHandler("chat.receive.after_process", name="maiidentity_observe", mode=HookMode.BLOCKING,
                 order=HookOrder.EARLY, error_policy=ErrorPolicy.SKIP)
    async def receive(self, message=None, **kwargs):
        if self.ready:
            try:
                self.resolver.observe(self._parse(message))
            except Exception:
                pass
        return None

    async def _inject(self, kwargs, stage):
        active = self.active
        resolver = self.resolver
        if not self.ready or active is None or not active.context.enabled:
            return None
        try:
            evidence = None
            if stage == "replyer" and kwargs.get("reply_message_id") and kwargs.get("session_id"):
                async def query(message_id, stream):
                    return await self.ctx.message.get_by_id(message_id, stream_id=stream)
                evidence, _ = await resolver.resolve(instance=active.plugin.instance_id, platform="qq",
                    namespace=active.identity.adapter_namespace, stream=kwargs["session_id"],
                    message_id=kwargs["reply_message_id"], query=query, parse=self._parse)
            if not self.ready or self.active is not active:
                # A prior turn may already contain our old identity block.
                # Replace it with unknown context rather than leaving a stale profile.
                if self.ready and self.projector is not None:
                    return self.projector.inject(kwargs, snapshot(stage=stage))
                return None
            person = match_person(active.identity.people, evidence)
            facts = snapshot(evidence, person, stage=stage)
            if stage=='planner' and 'extra_prompt' not in kwargs:
                from .typed_prompt import inject
                result=inject(self,kwargs,facts,'MaiIdentity')
                return result if 'modified_kwargs' in result else None
            return self.projector.inject(kwargs,facts)
        except Exception:
            return None  # Ordinary chat continues; raw prompt is never logged.

    @HookHandler("maisaka.replyer.before_request", name="maiidentity_replyer", error_policy=ErrorPolicy.SKIP)
    async def replyer(self, **kwargs):
        return await self._inject(kwargs, "replyer")

    @HookHandler("maisaka.planner.before_request", name="maiidentity_planner", error_policy=ErrorPolicy.SKIP)
    async def planner(self, **kwargs):
        return await self._inject(kwargs, "planner")

    @API("get_contract", public=True, version="1")
    async def get_contract(self, **kwargs):
        return descriptor(self.ready)

    @API("resolve_identity", public=True, version="1")
    async def resolve_identity(self, **kwargs):
        return PublicAPI().call("resolve_identity", **kwargs)

    @API("get_identity", public=True, version="1")
    async def get_identity(self, **kwargs):
        return PublicAPI().call("get_identity", **kwargs)

    @API("authorize", public=True, version="1")
    async def authorize(self, **kwargs):
        return PublicAPI().call("authorize", **kwargs)

    @API('authorize_vita_command',public=True,version='1')
    async def authorize_vita_command(self,**kwargs):
        # Retired patch interface: opaque references never grant access.
        return {'allowed':False,'reason':'LOCAL_COMMAND_REQUIRED'}

    @API('get_vita_policy',public=True,version='1')
    async def get_vita_policy(self,**kwargs):
        from .vita_management import evaluate
        active=self.active
        try:
            fields={'account_id','bot_account_id','route_scope','stream_id','action'}
            require(set(kwargs)==fields,'INVALID_ARGUMENT')
            from .routes import resolve
            route=await resolve(self.ctx,kwargs['stream_id'])
            require(route['account_id']==kwargs['bot_account_id'] and route.get('scope')==kwargs['route_scope'],'SCOPE_MISMATCH')
            require(self.ready and self.active is active,'NOT_READY')
            result=await owned_io(evaluate,self,**kwargs)
            require(self.ready and self.active is active,'NOT_READY')
            return result
        except Exception:
            return {'policy_version':1,'allowed':False}

    @API('get_public_social_context',public=True,version='1')
    async def get_public_social_context(self,**kwargs):
        from .social_context import public_context
        from ..integrations.api import envelope
        active=self.active
        try:
            require(set(kwargs)=={'stream_id','bot_account_id','route_scope'},'INVALID_ARGUMENT')
            from .routes import resolve
            route=await resolve(self.ctx,kwargs['stream_id'])
            require(route['account_id']==kwargs['bot_account_id'] and route.get('scope')==kwargs['route_scope'],'SCOPE_MISMATCH')
            require(self.ready and self.active is active,'NOT_READY')
            data=await owned_io(public_context,self,**kwargs)
            require(self.ready and self.active is active,'NOT_READY')
            return envelope(data=data)
        except Exception:return envelope(code='CONTEXT_UNAVAILABLE')

    @API("get_confirmed_relations", public=True, version="1")
    async def get_confirmed_relations(self, **kwargs):
        return PublicAPI().call("get_confirmed_relations", **kwargs)

    @API("build_context", public=True, version="1")
    async def build_context(self, **kwargs):
        return PublicAPI().call("build_context", **kwargs)

    @API("get_diagnostics", public=True, version="1")
    async def get_diagnostics(self, **kwargs):
        return PublicAPI().call("get_diagnostics", **kwargs)

    @Command("owner_auth_status", pattern=r"^/(?:owner_auth_status|maiidentity_status)\s*$", description="MaiIdentity 脱敏只读状态")
    async def status(self, stream_id="", **kwargs):
        if not stream_id:
            return True, "MaiIdentity status: no target stream", 1
        count = sum(p.enabled for p in self.active.identity.people) if self.ready and self.active else 0
        text = f"MaiIdentity {PLUGIN_VERSION}；"+("已就绪" if self.ready else "未启用")+f"；启用的固定身份 {count} 条；称呼不授予管理权限。"
        try:
            sent = await self.ctx.send.text(text, stream_id)
            return True, "public status sent" if sent is True else "normal send denied", 1
        except Exception:
            return True, "normal send unavailable", 1

    @Command('maiidentity_manage',pattern=r'^/maiidentity(?:\s|$)',description='固定身份帮助与运行状态')
    async def self_command(self,text='',stream_id='',**kwargs):
        if text.strip() in ('/maiidentity','/maiidentity status'):
            return await self.status(stream_id=stream_id)
        if text.strip() in ('/maiidentity help','/maiidentity 帮助'):
            if not stream_id:return True,'no target stream',2
            help_text=('MaiIdentity：\n/maiidentity status 查看状态\n'
                '在配置的 identity.people 名单填写 QQ、nickname 和可选 prompt_template，无需登记。\n'
                'Vita 管理账号由 management.vita_admin_accounts 配置，固定称呼不授予管理权。')
            try:await self.ctx.send.text(help_text,stream_id)
            except Exception:pass
            return True,'help through normal permissions',2
        from .local_command import validate
        from ..shared.core import Denied
        from .routes import command_route
        target=''
        active=self.active
        envelope={**kwargs,'text':text,'stream_id':stream_id}
        try:
            route=await command_route(self.ctx,envelope)
        except Exception:
            return True,'MaiIdentity 未执行：ROUTE_UNRESOLVED；无法核对当前 Host 会话',2
        try:
            # A verified destination permits a generic receipt, not a mutation.
            target=route['stream_id']
            require(self.ready and self.active is active,'NOT_READY')
            validate(self,envelope)
            message='MaiIdentity：此命令不可用。固定身份请在配置的 identity.people 名单中设置；使用 /maiidentity help 查看帮助。'
        except Denied as exc:
            message='MaiIdentity 未执行：'+exc.code
            hints={'UNTRUSTED_CONTEXT':'命令消息身份字段不一致，请检查适配器消息。',
                'IDENTITY_UNRESOLVED':'无法确认当前消息作者，未执行操作。',
                'NOT_READY':'插件正在重载或尚未就绪，请稍后重试。'}
            if exc.code in hints:message+='；'+hints[exc.code]
            if not target: return True,message,2
        except Exception:
            message='MaiIdentity 未执行：服务暂不可用，操作未确认；请查看插件日志。'
            if not target:return True,message,2
        try:
            sent=await self.ctx.send.text(message,target)
            return True,'self command handled' if sent is True else 'normal send denied: '+message,2
        except Exception:
            return True,'normal send unavailable',2
