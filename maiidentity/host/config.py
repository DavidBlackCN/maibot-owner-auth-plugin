from typing import Literal
import unicodedata
from maibot_sdk import PluginConfigBase
from pydantic import ConfigDict, Field, field_validator
from ..shared.core import opaque, qq


class Section(PluginConfigBase):
    model_config = ConfigDict(extra="forbid", strict=True)


class PluginSection(Section):
    enabled: bool = Field(default=True, description="启用插件")
    config_version: Literal["4"] = "4"


class PersonEntry(Section):
    qq: str = Field(description="此人的 QQ 号；只用于匹配消息作者", json_schema_extra={"label": "QQ 号"})
    nickname: str = Field(min_length=1, max_length=40, description="角色对这个人的固定称呼，如妈妈、朋友", json_schema_extra={"label": "固定称呼"})
    prompt_template: str = Field(default="", max_length=1000, description="可选的相处说明；留空使用自然表达，可用 {nickname} 引用称呼", json_schema_extra={"label": "相处说明", "x-widget": "textarea"})
    group_id: str = Field(default="", description="只在指定群生效；留空适用于群聊和私聊", json_schema_extra={"label": "适用群号"})
    enabled: bool = Field(default=True, description="停用后保留此条配置", json_schema_extra={"label": "启用"})

    @field_validator("qq", "group_id")
    @classmethod
    def valid_account(cls, value, info):
        from ..shared.core import qq
        if info.field_name == "group_id" and value == "":
            return value
        return qq(value)

    @field_validator("nickname")
    @classmethod
    def valid_name(cls, value):
        if value != value.strip() or not value or any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("固定称呼不能为空、含控制字符或首尾空白")
        return value


class IdentitySection(Section):
    adapter_namespace: str = Field(default="host-qq", description="消息来源命名空间，通常保持默认")
    route_scope: str = Field(default="", description="接入端 scope；留空只匹配未设置 scope 的会话")
    people: list[PersonEntry] = Field(default_factory=list, max_length=200,
        description="固定身份名单；QQ 和称呼必填，同一 QQ 的群专属设置优先", json_schema_extra={"label": "固定身份名单"})

    @field_validator("adapter_namespace", "route_scope")
    @classmethod
    def valid_scope(cls, value, info):
        if info.field_name == "route_scope" and value == "":
            return value
        return opaque(value)

    @field_validator("people")
    @classmethod
    def unique_people(cls, value):
        keys = [(entry.qq, entry.group_id) for entry in value]
        if len(keys) != len(set(keys)):
            raise ValueError("同一 QQ 在同一适用范围只能配置一次")
        return value


class ContextSection(Section):
    enabled: bool = Field(default=True, description="向回复模型提供固定身份提示")
    budget_bytes: int = Field(default=2048, ge=1200, le=8192, description="身份提示的最大字节数，通常保持默认")
    cache_ttl_seconds: int = Field(default=300, ge=10, le=3600, description="准确消息作者缓存时间，单位秒")


class ManagementSection(Section):
    admin_accounts: list[str] = Field(default_factory=list, max_length=16,
        description="管理员 QQ 名单；允许使用已接入的 Vita 管理命令，留空无人获权", json_schema_extra={"label": "管理员 QQ"})

    @field_validator("admin_accounts")
    @classmethod
    def accounts(cls, value):
        for account in value:
            qq(account)
        if len(set(value)) != len(value):
            raise ValueError("管理员 QQ 不能重复")
        return value


class MaiIdentityConfig(Section):
    plugin: PluginSection = Field(default_factory=PluginSection)
    identity: IdentitySection = Field(default_factory=IdentitySection)
    context: ContextSection = Field(default_factory=ContextSection)
    management: ManagementSection = Field(default_factory=ManagementSection)
