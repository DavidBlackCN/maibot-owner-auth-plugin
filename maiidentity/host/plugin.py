from __future__ import annotations

from pathlib import Path
import asyncio
from ..runtime_versions import runtime_supported

from maibot_sdk import API, Command, HookHandler, MaiBotPlugin
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder

from .. import OLD_PLUGIN_ID, PLUGIN_VERSION
from ..context.projection import Projector, snapshot, match_person
from ..identity.messages import MessageResolver, host_message
from ..integrations.api import descriptor
from ..shared.core import qq, require
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
        self.db = self.lease = self.active = None
        self.resolver = self.projector = None
        self.instance_id = None
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
            self.lease = WriterLease(data / "writer.lock")
            await owned_io(self.lease.acquire)
            path = data / "identity.db"
            # Assign inside the joined worker so cancellation cannot discard an
            # opened connection before the failure cleanup can see it.
            def open_database():
                self.db = Database(path, create=not path.exists())
            await owned_io(open_database)
            self.loaded_config = cfg.model_copy(deep=True)
            self.active = cfg.model_copy(deep=True)
            self.instance_id, ownership_key = await owned_io(self.db.context_state)
            self.resolver = MessageResolver(ttl=cfg.context.cache_ttl_seconds)
            self.projector = Projector(cfg.context.budget_bytes, ownership_key=ownership_key)
            self.ready = True
        except BaseException:
            await self.on_unload()
            raise

    async def on_unload(self):
        self.ready = False
        try:
            if self.resolver:
                self.resolver.close()
            if self.projector:
                self.projector.close()
        finally:
            try:
                if self.db:
                    await owned_io(self.db.close)
            finally:
                self.loaded_config = None
                self.instance_id = None
                if self.lease:
                    self.lease.release()
                self.db = self.lease = self.active = None
                self.resolver = self.projector = None

    async def on_config_update(self, scope, config_data, version):
        if scope != "self":
            return
        try:
            new = MaiIdentityConfig.model_validate(config_data)
        except BaseException:
            await self.on_unload()
            raise
        if self.active is None:
            return
        if not new.plugin.enabled:
            await self.on_unload()
            return
        # No remote writes or cached grants: swap the complete validated view.
        # In-flight route/message reads check identity of this view before use.
        route_changed = (new.identity.adapter_namespace, new.identity.route_scope) != (self.active.identity.adapter_namespace, self.active.identity.route_scope)
        self.active = new.model_copy(deep=True)
        self.loaded_config = new.model_copy(deep=True)
        if route_changed:
            self.resolver.close()
        self.resolver.ttl = new.context.cache_ttl_seconds
        self.resolver.purge()
        self.projector.budget = new.context.budget_bytes

    def _parse(self, raw):
        # Only official Host receive/query/Command serializers reach here.
        # The adapter's route account takes precedence over the global fallback.
        bot = qq(raw.get('account_id')) if type(raw) is dict else ''
        return host_message(raw, instance=self.instance_id,
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
                    return await asyncio.wait_for(self.ctx.message.get_by_id(message_id, stream_id=stream), 2)
                evidence, _ = await resolver.resolve(instance=self.instance_id, platform="qq",
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

    @API('is_admin', public=True, version='1')
    async def is_admin(self, **kwargs):
        from .vita_management import administrator
        active = self.active
        try:
            require(set(kwargs) == {'account_id', 'bot_account_id', 'route_scope', 'stream_id'}, 'INVALID_ARGUMENT')
            from .routes import resolve
            route = await resolve(self.ctx, kwargs['stream_id'])
            require(route['account_id'] == kwargs['bot_account_id'] and route.get('scope') == kwargs['route_scope'], 'SCOPE_MISMATCH')
            require(self.ready and self.active is active, 'NOT_READY')
            return {'is_admin': administrator(self, **kwargs)}
        except Exception:
            return {'is_admin': False}

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
            result=evaluate(self,**kwargs)
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
            data=public_context(self,**kwargs)
            require(self.ready and self.active is active,'NOT_READY')
            return envelope(data=data)
        except Exception:return envelope(code='CONTEXT_UNAVAILABLE')

    @Command("maiidentity_status", pattern=r"^/maiidentity_status\s*$", description="MaiIdentity 脱敏只读状态")
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
                'Vita 管理账号由 management.admin_accounts 配置，固定称呼不授予管理权。')
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
