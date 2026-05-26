# MaiBot 插件迁移指南：旧版 SDK → 1.0.0 新版 SDK

> **适用场景**：将基于 MaiBot 0.11.x/0.12.x 旧版 SDK 编写的第三方插件迁移至 MaiBot 1.0.0 + maibot-plugin-sdk 2.x。
>
> **最后更新**：2026-05-26
>
> **参考文档**：[MaiBot 插件开发指南](https://docs.mai-mai.org/develop/plugin-dev/)、[Vibe Coding 指南](https://docs.mai-mai.org/develop/plugin-dev/vibe-coding.html)

---

## 1. 迁移前必读：核心差异一览

| 方面 | 旧 SDK (0.11.x/0.12.x) | 新 SDK (1.0.0 / maibot-sdk 2.x) |
|------|------------------------|----------------------------------|
| **SDK 包** | 从主程序 `src.plugin_system` 导入 | `pip install maibot-plugin-sdk`，代码中 `from maibot_sdk import ...` |
| **插件基类** | `BasePlugin` | `MaiBotPlugin` |
| **注册方式** | `@register_plugin` 装饰器 | `create_plugin()` 工厂函数（模块顶层导出） |
| **生命周期** | `on_plugin_load()` / `on_plugin_unload()` / `on_plugin_enable()` / `on_plugin_disable()` | `on_load()` / `on_unload()` / `on_config_update(scope, config_data, version)` |
| **配置系统** | `config_schema` dict + `ConfigField(type=..., default=...)` + 手动 `_generate_and_save_default_config()` | `PluginConfigBase` 子类 + `Field(default=..., description=...)`，自动生成 TOML 和 WebUI Schema |
| **事件处理** | 继承 `BaseEventHandler` 类，覆写 `execute()`，在 `get_plugin_components()` 中注册 | `@EventHandler` 装饰器，直接装饰插件类中的 async 方法 |
| **流程拦截** | `@WorkflowStep`（已在 2.0 移除）、monkey-patching 内部模块 | `@HookHandler` 装饰器，订阅命名 Hook 点 |
| **日志** | `get_logger("name")` 获取全局 logger | `self.ctx.logger`（实例上下文自动注入） |
| **依赖管理** | 插件代码中自建 `_bootstrap_install_if_missing()` 手动安装 | `_manifest.json` 的 `dependencies` 数组声明，Host 自动解析安装 |
| **配置读取** | `self.get_config("section.key", default)` | `self.config.section.key`（强类型）或 `self.get_plugin_config_data()`（dict） |
| **消息对象** | `MaiMessages` 对象，`.message_base_info` / `.plain_text` 属性 | `dict` 类型，`.get("message_base_info", {})` 访问 |
| **Manifest 版本** | `manifest_version: 1` | `manifest_version: 2`（严格 schema 校验） |
| **插件 ID** | 自由格式（如 `khIqwq.owner_auth_plugin`） | 必须匹配 `^[a-z0-9]+(?:[.-][a-z0-9]+)+$`（如 `com.example.my-plugin`） |

---

## 2. `_manifest.json` 迁移 (v1 → v2)

### 2.1 新旧字段对照

```
manifest_version:  1          →  2 （固定值）
id:                自由格式    →  必须匹配 ^[a-z0-9]+(?:[.-][a-z0-9]+)+$
version:           三段式      →  三段式（不变）
name:              ✅          →  ✅（不变）
description:       ✅          →  ✅（不变）
author.name:       ✅          →  ✅（不变）
author.url:        任意        →  必须以 http:// 或 https:// 开头
license:           ✅          →  ✅（不变）
homepage_url:      ❌ 删除     →  移入 urls.homepage
repository_url:    ❌ 删除     →  移入 urls.repository（必填）
keywords:          ❌ 删除     →  不再支持
categories:        ❌ 删除     →  不再支持
plugin_info:       ❌ 删除     →  组件由装饰器自动注册，不在此声明
default_locale:    ❌ 删除     →  移入 i18n.default_locale
locales_path:      ❌ 删除     →  移入 i18n.locales_path
host_application:  仅 min_version →  min_version + max_version（闭区间）
sdk:               ❌ 无       →  ✅ 新增，含 min_version + max_version
dependencies:      ❌ 无       →  ✅ 新增数组
capabilities:      ❌ 无       →  ✅ 新增字符串数组
i18n:              ❌ 无       →  ✅ 新增对象
```

### 2.2 新增必填字段

```json
{
  "sdk": {
    "min_version": "2.5.1",
    "max_version": "2.99.99"
  }
}
```

```json
{
  "host_application": {
    "min_version": "1.0.0",
    "max_version": "1.99.99"
  }
}
```

```json
{
  "dependencies": [
    {
      "type": "python_package",
      "name": "包名",
      "version_spec": ">=1.0.0"
    },
    {
      "type": "plugin",
      "id": "com.example.other-plugin",
      "version_spec": ">=1.0.0,<2.0.0"
    }
  ]
}
```

- `type` 为 `python_package` 或 `plugin`
- `name` 仅允许字母、数字、点号、下划线、横线
- `version_spec` 使用 PEP 440 风格

```json
{
  "capabilities": ["send_message"]
}
```

常用值：`send_message`、`read_message`、`manage_plugin`、`file_access` 等。

```json
{
  "i18n": {
    "default_locale": "zh-CN",
    "locales_path": "_locales"
  }
}
```

### 2.3 删除的字段

以下字段在 v2 manifest 中**不再存在**，直接删除即可：

- `keywords` — 数组
- `categories` — 数组
- `plugin_info` — 整个对象（`is_built_in`、`plugin_type`、`components`、`features` 等）
- `homepage_url` — 扁平字段，迁移到 `urls.homepage`
- `repository_url` — 扁平字段，迁移到 `urls.repository`

### 2.4 `urls` 对象

```json
{
  "urls": {
    "repository": "https://github.com/author/plugin-repo",
    "homepage": "https://example.com",
    "documentation": "https://docs.example.com",
    "issues": "https://github.com/author/plugin-repo/issues"
  }
}
```

`repository` 为**必填**，其余可选。所有 URL 必须以 `http://` 或 `https://` 开头。

### 2.5 插件 ID 格式

旧 ID（如 `khIqwq.owner_auth_plugin`）可能不符合新规范。新规范要求：

```
^[a-z0-9]+(?:[.-][a-z0-9]+)+$
```

即：小写字母/数字开头 + 至少一段点号或横线分隔 + 小写字母/数字。推荐格式：`com.<author>.<plugin-name>`。

### 2.6 完整 v2 Manifest 模板

```json
{
  "manifest_version": 2,
  "id": "com.example.my-plugin",
  "version": "2.0.0",
  "name": "我的插件",
  "description": "插件功能描述",
  "author": {
    "name": "作者名",
    "url": "https://github.com/author"
  },
  "license": "MIT",
  "urls": {
    "repository": "https://github.com/author/my-plugin",
    "homepage": "https://github.com/author"
  },
  "host_application": {
    "min_version": "1.0.0",
    "max_version": "1.99.99"
  },
  "sdk": {
    "min_version": "2.5.1",
    "max_version": "2.99.99"
  },
  "dependencies": [
    {
      "type": "python_package",
      "name": "typing-extensions",
      "version_spec": ">=4.8.0"
    }
  ],
  "capabilities": ["send_message"],
  "i18n": {
    "default_locale": "zh-CN",
    "locales_path": "_locales"
  }
}
```

---

## 3. `plugin.py` 代码迁移

### 3.1 导入语句

**旧代码（删除所有以下导入）：**

```python
# ❌ 不要导入这些
import os, sys, subprocess, shutil, importlib, importlib.util
from ...src.plugin_system import BasePlugin, register_plugin, ...
from src.common.logger import get_logger
from src.person_info.person_info import Person
from src.chat.utils.prompt_builder import global_prompt_manager
```

**新代码：**

```python
# ✅ 只从这三个来源导入
import time
from typing import Any, TypedDict

from maibot_sdk import (
    EventHandler,
    Field,
    HookHandler,
    MaiBotPlugin,
    PluginConfigBase,
)
from maibot_sdk.types import EventType, HookMode, HookOrder
```

规则：
- 标准库（`time`、`typing` 等）
- 第三方库
- `maibot_sdk` 及其子模块

**禁止**直接导入 `src/` 下的任何模块。

### 3.2 依赖安装代码移除

**旧代码中常见的依赖自安装模式必须删除：**

```python
# ❌ 删除整个依赖安装逻辑
ALIYUN_PYPI = os.environ.get("ALIYUN_PYPI", "...")
def _ensure_pip_ready(): ...
def _pypi_install(spec): ...
def _bootstrap_install_if_missing(dep_spec): ...
```

改为在 `_manifest.json` 的 `dependencies` 中声明，Host 会自动处理。

### 3.3 插件类和注册方式

**旧代码：**

```python
@register_plugin
class MyPlugin(BasePlugin):
    plugin_name: str = "my_plugin"
    enable_plugin: bool = True

    def on_plugin_load(self) -> None: ...
    def on_plugin_unload(self) -> None: ...
    def on_plugin_enable(self) -> None: ...
    def on_plugin_disable(self) -> None: ...
    def get_plugin_components(self): ...
```

**新代码：**

```python
class MyPlugin(MaiBotPlugin):
    """插件描述。"""
    config_model = MyPluginConfig  # 必须声明

    async def on_load(self) -> None: ...
    async def on_unload(self) -> None: ...
    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None: ...


# 模块顶层导出工厂函数
def create_plugin() -> MyPlugin:
    return MyPlugin()
```

关键规则：
- **不要**使用 `@register_plugin` 装饰器
- **必须**在模块顶层导出 `create_plugin()` 函数
- **必须**实现 `on_load`、`on_unload`、`on_config_update` 三个 async 方法
- `on_config_update(scope, config_data, version)` — `scope == "self"` 时表示插件自身配置变更

### 3.4 生命周期方法详解

```python
class MyPlugin(MaiBotPlugin):
    config_model = MyPluginConfig

    async def on_load(self) -> None:
        """Runner 注入 PluginContext 后调用。此时 self.ctx 已可用。"""
        # 初始化实例属性
        self._cache: dict[str, Any] = {}
        self.ctx.logger.info("插件已加载")

    async def on_unload(self) -> None:
        """插件卸载前调用。清理所有资源。"""
        self._cache.clear()
        self.ctx.logger.info("插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置热重载回调。scope 为 "self"/"bot"/"model"。"""
        if scope == "self":
            self.ctx.logger.info("插件配置已更新: version=%s", version)
```

注意：
- `on_load` 中 `self.ctx` **已可用**，可直接使用 `self.ctx.logger`、`self.config` 等
- `on_unload` 中仍可使用 `self.ctx`，但应尽快完成清理
- `on_config_update` 的 `scope == "self"` 总是触发，不需要额外订阅

---

## 4. 配置模型迁移

### 4.1 旧配置模式

```python
# ❌ 旧代码：手动 dict schema
config_schema = {
    "plugin": {
        "enabled": ConfigField(type=bool, default=True, description="是否启用"),
        "version": ConfigField(type=str, default="1.0.0", description="版本"),
    },
    "my_section": {
        "some_key": ConfigField(type=str, default="hello", description="某配置项"),
    },
}

# 读取配置
value = self.get_config("my_section.some_key", "default")
```

### 4.2 新配置模式

```python
# ✅ 新代码：PluginConfigBase + Field
from maibot_sdk import Field, PluginConfigBase

class MySectionConfig(PluginConfigBase):
    """配置节描述。"""
    __ui_label__ = "我的配置"      # WebUI 显示名
    __ui_icon__ = "settings"        # WebUI 图标
    __ui_order__ = 1                # 排序

    some_key: str = Field(default="hello", description="某配置项")
    a_number: int = Field(default=42, description="一个数字")
    a_flag: bool = Field(default=True, description="开关")

class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="2.0.0", description="配置版本")

class MyPluginConfig(PluginConfigBase):
    """顶层配置。"""
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    my_section: MySectionConfig = Field(default_factory=MySectionConfig)
```

### 4.3 列表式配置（替代旧版的动态 user1/user2/...）

旧版常见模式：通过 `User` 数字动态生成 `[user1]`、`[user2]` 等节。在新 SDK 中用 **TOML 数组表** 替代：

**新代码：**

```python
class UserConfig(PluginConfigBase):
    """单个用户的配置。"""
    __ui_label__ = "用户"
    nickname: str = Field(default="用户", description="昵称")
    owner_qq: int = Field(default=0, description="QQ号")
    prompt_template: str = Field(default="...", description="提示词模板")

class OwnerAuthConfig(PluginConfigBase):
    users: list[UserConfig] = Field(
        default_factory=lambda: [UserConfig()],
        description="用户列表",
    )
```

**对应 TOML：**

```toml
[[owner_auth.users]]
nickname = "主人"
owner_qq = 123456789
prompt_template = "..."

[[owner_auth.users]]
nickname = "妈妈"
owner_qq = 987654321
prompt_template = "..."
```

### 4.4 配置读取方式

```python
# ✅ 强类型访问（推荐）
if self.config.plugin.enabled:
    do_something()

cfg = self.config.owner_auth
for user in cfg.users:
    print(user.nickname, user.owner_qq)

# ✅ 字典访问（兼容）
raw = self.get_plugin_config_data()
value = raw.get("section", {}).get("key", "default")
```

注意：
- 声明 `config_model` 后，`self.config` 返回强类型配置实例
- `self.get_plugin_config_data()` 始终可用，返回原始 `dict`

---

## 5. 事件处理迁移（BaseEventHandler → @EventHandler）

### 5.1 旧模式

```python
# ❌ 旧代码：继承 BaseEventHandler 类
class MyEventHandler(BaseEventHandler):
    event_type: EventType = EventType.ON_MESSAGE
    handler_name: str = "my_handler"
    handler_description: str = "描述"
    weight: int = 1000
    intercept_message: bool = False

    async def execute(self, message: MaiMessages | None) -> tuple[...]:
        user_id = message.message_base_info.get("user_id")
        text = message.plain_text
        # ... 处理逻辑 ...
        return True, True, "ok", None, message

# 在插件类中注册
def get_plugin_components(self):
    return [(MyEventHandler.get_handler_info(), MyEventHandler)]
```

### 5.2 新模式

```python
# ✅ 新代码：@EventHandler 装饰器，直接写在插件类中
class MyPlugin(MaiBotPlugin):
    @EventHandler(
        "my_handler",                    # name（必填）
        description="事件处理器描述",
        event_type=EventType.ON_MESSAGE, # 事件类型
        weight=1000,                     # 权重，越高越优先
    )
    async def handle_message(self, message: dict[str, Any], **kwargs: Any) -> None:
        # message 是 dict 类型
        msg_base = message.get("message_base_info", {})
        user_id = msg_base.get("user_id")
        text = message.get("plain_text", "")
        # ... 处理逻辑 ...
```

### 5.3 EventType 对照

旧 SDK 和新 SDK 的 `EventType` 枚举值基本一致：

| 事件 | 用途 |
|------|------|
| `ON_MESSAGE` | 消息处理阶段 |
| `ON_MESSAGE_PRE_PROCESS` | 消息预处理（过滤/拦截最佳时机） |
| `ON_START` | 插件启动 |
| `ON_STOP` | 插件停止 |
| `POST_LLM` / `AFTER_LLM` | LLM 调用后 |
| `POST_SEND` / `AFTER_SEND` | 消息发送后 |

### 5.4 消息对象差异

**旧**：`MaiMessages` 对象，属性访问（如 `message.message_base_info`、`message.plain_text`）

**新**：`dict` 类型，用 `.get()` 访问：

```python
msg_base = message.get("message_base_info", {})
user_id = msg_base.get("user_id")
user_nickname = str(msg_base.get("user_nickname", "未知用户") or "未知用户")
user_cardname = str(msg_base.get("user_cardname", "") or "")
raw_message = msg_base.get("raw_message", "")
plain_text = message.get("plain_text", "")
```

---

## 6. Hook 系统迁移（替代 monkey-patching 和 WorkflowStep）

### 6.1 核心概念

MaiBot 1.0.0 使用 `@HookHandler` 替代旧版的 monkey-patching 和 `@WorkflowStep`。Hook 是预定义的命名扩展点，插件通过订阅 Hook 名称来拦截或观察主流程。

#### @HookHandler 装饰器签名

```python
from maibot_sdk import HookHandler
from maibot_sdk.types import HookMode, HookOrder

@HookHandler(
    "hook.name",                     # Hook 名称（必填，必须是已注册的 Hook）
    *,
    name: str = "",                  # 组件名称，留空时使用方法名
    description: str = "",           # 组件描述
    mode: HookMode = HookMode.BLOCKING,  # BLOCKING 或 OBSERVE
    order: HookOrder = HookOrder.NORMAL, # EARLY / NORMAL / LATE
    timeout_ms: int = 0,             # 超时（毫秒），0 = 使用默认值
)
```

#### 两种模式

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `BLOCKING` | 串行执行，可修改 kwargs，可 abort | 拦截消息、修改参数、注入提示词 |
| `OBSERVE` | 后台并发，只读，返回值被忽略 | 日志记录、统计分析 |

#### 返回值（仅 BLOCKING 模式有效）

```python
# 继续执行，传递修改后的参数
return {"action": "continue", "modified_kwargs": kwargs}

# 终止调用链
return {"action": "abort"}
```

### 6.2 常用 Hook 点

| Hook 名称 | 触发时机 | 能否 abort | 能否改参 | 典型用途 |
|-----------|----------|-----------|----------|----------|
| `chat.receive.before_process` | 入站消息处理前 | ✅ | ✅ | 消息过滤、拦截 |
| `chat.receive.after_process` | 入站消息预处理完成后 | ✅ | ✅ | 消息改写 |
| `maisaka.replyer.before_request` | Replyer 请求模型前 | ❌ | ✅ | 注入 `extra_prompt`、切换模型 |
| `maisaka.replyer.before_model_request` | 构造完 messages、请求模型前 | ❌ | ✅ | 改写 messages 列表 |
| `maisaka.replyer.after_response` | Replyer 收到模型响应后 | ❌ | ✅ | 改写回复 |
| `maisaka.planner.before_request` | Planner 请求模型前 | ❌ | ✅ | 修改 tool_definitions |
| `send_service.before_send` | 发送消息前 | ✅ | ✅ | 发送前审计 |
| `send_service.after_send` | 发送完成后 | ❌ | ❌ | 发送后日志 |

### 6.3 迁移场景 1：Monkey-patching → @HookHandler

这是最常见的迁移场景。旧插件常通过 monkey-patching 拦截内部方法（如 `format_prompt`）。

**旧模式（monkey-patching）：**

```python
# ❌ 旧代码
from src.chat.utils.prompt_builder import global_prompt_manager
import types

_original_format_prompt = global_prompt_manager.format_prompt

async def _wrapped_format_prompt(self, name, **kwargs):
    result = await _original_format_prompt(name, **kwargs)
    if name == "replyer_prompt":
        # 注入自定义提示词
        result = custom_prefix + result
    return result

global_prompt_manager.format_prompt = types.MethodType(
    _wrapped_format_prompt, global_prompt_manager
)
```

**新模式（@HookHandler）：**

```python
# ✅ 新代码：在插件类中使用 @HookHandler
class MyPlugin(MaiBotPlugin):

    @HookHandler(
        "maisaka.replyer.before_request",
        mode=HookMode.BLOCKING,
        name="my_prompt_inject",
        description="在回复前注入自定义提示词",
        order=HookOrder.EARLY,
    )
    async def inject_prompt(self, **kwargs: Any) -> dict[str, Any]:
        prefix = self._build_custom_prompt()
        if prefix:
            existing = kwargs.get("extra_prompt", "") or ""
            kwargs["extra_prompt"] = existing + prefix
            return {"action": "continue", "modified_kwargs": kwargs}
        return {"action": "continue", "modified_kwargs": kwargs}
```

关键差异：
- 不再需要导入内部模块、保存/恢复原始方法
- 不再需要 `types.MethodType` 绑定
- 通过 `extra_prompt` 字段注入（MaiBot 会自动将其追加到模型 prompt）
- 卸载时无需手动恢复 — SDK 自动管理生命周期

### 6.4 迁移场景 2：WorkflowStep → @HookHandler

`@WorkflowStep` 在 SDK 2.0 中**已完全移除**，调用会直接抛 `RuntimeError`。

```python
# ❌ 旧代码
@WorkflowStep(stage="pre_process", blocking=True)
async def on_pre_process(self, **kwargs): ...

# ✅ 新代码
@HookHandler("chat.receive.before_process", mode=HookMode.BLOCKING)
async def on_pre_process(self, **kwargs): ...
```

| 旧参数 | 新参数 |
|--------|--------|
| `stage="pre_process"` | `"chat.receive.before_process"` |
| `blocking=True` | `mode=HookMode.BLOCKING` |
| `observe=True` | `mode=HookMode.OBSERVE` |
| `priority=10` | `order=HookOrder.EARLY` |

---

## 7. 常见迁移陷阱

### 7.1 不要在 `on_load` 中做耗时操作

`on_load` 是 async 方法，但 Runner 会等待它完成。不要在其中执行：
- 网络请求（除非有超时）
- 大文件 I/O
- 长时间运行的后台任务初始化

如果需要后台任务，用 `asyncio.create_task` 并妥善管理生命周期。

### 7.2 不要修改 `message` 对象本身

在新 SDK 的 `@EventHandler` 中，`message` 是一个 `dict`。如需修改消息内容并影响下游，应使用 `@HookHandler("chat.receive.after_process")` 的 BLOCKING 模式。

### 7.3 配置字段名保持一致

`PluginConfigBase` 的字段名直接映射到 TOML 键名。如果旧配置使用 `enable_auth`，新配置的字段名也必须用 `enable_auth`（不能用 `enableAuth`）。

### 7.4 全局缓存迁移为实例属性

旧插件常见 `_global_auth_cache: dict = {}` 全局变量。在新 SDK 中改为实例属性：

```python
class MyPlugin(MaiBotPlugin):
    async def on_load(self) -> None:
        self._cache: dict[str, Any] = {}  # ✅ 实例属性
```

### 7.5 处理 `override` 导入

旧代码常从 `typing` 或 `typing_extensions` 导入 `override`。新 SDK 不再需要，直接删除相关代码。

### 7.6 日志方法

```python
# ❌ 旧代码
logger = get_logger("my_plugin")
logger.info("消息")

# ✅ 新代码
self.ctx.logger.info("消息")
```

日志名称自动为 `plugin.<plugin_id>`。

### 7.7 不要在 `__init__` 中做初始化

旧 SDK 在 `__init__` 中做大量初始化。新 SDK 中 `__init__` 由 `create_plugin()` 调用时执行，此时 `self.ctx` 尚不可用。所有需要 `self.ctx` 的初始化放在 `on_load` 中。

---

## 8. 迁移检查清单

逐项自检，确保迁移完整：

### Manifest

- [ ] `manifest_version` 设为 `2`
- [ ] `id` 符合 `^[a-z0-9]+(?:[.-][a-z0-9]+)+$` 格式
- [ ] `version` 为严格三段式语义版本
- [ ] `author.url` 以 `http://` 或 `https://` 开头
- [ ] 添加 `sdk` 字段（`min_version` + `max_version`）
- [ ] 添加 `host_application.max_version`
- [ ] `homepage_url` / `repository_url` 移入 `urls` 对象
- [ ] `urls.repository` 必填
- [ ] 添加 `dependencies` 数组（声明所有 Python 包依赖）
- [ ] 添加 `capabilities` 数组（至少 `["send_message"]`）
- [ ] 添加 `i18n` 对象，`default_locale` 推荐 `zh-CN`
- [ ] 删除 `keywords`、`categories`、`plugin_info`

### 插件代码

- [ ] 只从 `maibot_sdk`、标准库、第三方库导入
- [ ] 删除所有 `src.*` 直接导入
- [ ] 删除自建依赖安装逻辑（`_bootstrap_install_if_missing` 等）
- [ ] 插件类继承 `MaiBotPlugin`
- [ ] 声明 `config_model`
- [ ] 实现 `on_load()` / `on_unload()` / `on_config_update()`
- [ ] 模块顶层导出 `create_plugin()` 工厂函数
- [ ] 配置使用 `PluginConfigBase` + `Field`
- [ ] 事件处理使用 `@EventHandler` 装饰器
- [ ] 流程拦截使用 `@HookHandler` 装饰器（不再 monkey-patching）
- [ ] 日志使用 `self.ctx.logger`
- [ ] 全局状态改为实例属性
- [ ] 删除 `override` 导入和 `@register_plugin` 装饰器
- [ ] 删除不再需要的辅助文件（如 `patch_manager.py`）

### 配置模型

- [ ] 推荐保留 `[plugin]` 分组，包含 `enabled` 与 `config_version`
- [ ] 字段类型与旧配置兼容（bool → bool, str → str, int → int）
- [ ] 多条目配置使用 `list[SubConfig]` + `default_factory`
- [ ] `__ui_label__`、`__ui_icon__`、`__ui_order__` 已设置

### 文档

- [ ] README 更新版本号和兼容性说明
- [ ] README 中的配置示例与新的 TOML 结构一致
- [ ] README 移除补丁管理相关描述
- [ ] 许可证与 `_manifest.json` 中的 `license` 一致

---

## 9. 快速参考

### 9.1 核心导入

```python
from maibot_sdk import (
    EventHandler,
    Field,
    HookHandler,
    MaiBotPlugin,
    PluginConfigBase,
)
from maibot_sdk.types import (
    EventType,
    HookMode,
    HookOrder,
    ToolParameterInfo,
    ToolParamType,
)
```

### 9.2 最小插件骨架

```python
from typing import Any
from maibot_sdk import Field, MaiBotPlugin, PluginConfigBase

class PluginSectionConfig(PluginConfigBase):
    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="2.0.0", description="配置版本")

class MyPluginConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)

class MyPlugin(MaiBotPlugin):
    config_model = MyPluginConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        if scope == "self":
            self.ctx.logger.info("配置已更新: version=%s", version)

def create_plugin() -> MyPlugin:
    return MyPlugin()
```

### 9.3 能力代理速查

通过 `self.ctx` 访问：

| 代理 | 用途 |
|------|------|
| `self.ctx.logger` | 日志记录 |
| `self.ctx.send.text(msg, stream_id)` | 发送文本消息 |
| `self.ctx.config` | 插件配置 |
| `self.ctx.db` | 数据库操作 |
| `self.ctx.llm` | LLM 调用 |
| `self.ctx.person` | 用户信息查询 |
| `self.ctx.api` | 调用其他插件 API |
| `self.ctx.gateway` | 消息网关管理 |
| `self.ctx.chat` | 聊天流管理 |
| `self.ctx.message` | 历史消息查询 |

---

> **提示**：迁移完成后，建议将插件放入 MaiBot 1.0.0 的 `plugins/` 目录，启动 Bot 观察日志，并通过 WebUI 确认插件可见、可启用、配置可编辑。
