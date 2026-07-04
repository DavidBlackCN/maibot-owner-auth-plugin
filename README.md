# 用户身份验证插件（自用 fork）

> 这是 [khiqwq/owner_auth_plugin](https://github.com/khiqwq/owner_auth_plugin) 的自用 fork。
>
> 本仓库最初是因为原插件尚未适配新版 MaiBot SDK，临时迁移到 MaiBot 1.0 / maibot_sdk 2.x 后自用。现在原项目已经完成新版 SDK 适配，**建议优先使用原插件**。本仓库只保留个人自用修改，不作为推荐分发版本。

## 当前版本

- 插件版本：`2.1.0`
- 适配 MaiBot：`1.0.0` ~ `1.99.x`
- 适配 SDK：`maibot_sdk 2.x`
- 原项目：<https://github.com/khiqwq/owner_auth_plugin>
- 本 fork：<https://github.com/DavidBlackCN/maibot-owner-auth-plugin>

## 功能

- 只按 QQ 号验证身份，不依赖昵称或群名片。
- 支持多个用户槽位，每个用户可独立配置 QQ、昵称、限制群聊和提示词模板。
- 支持同一 QQ 的全局配置与群专属配置，群专属优先。
- 在 `maisaka.replyer.before_request` 回复前通过 `extra_prompt` 注入身份提示词。
- 可选在 `maisaka.planner.before_request` 行动规划阶段注入身份提示词。
- 非用户安全提醒默认关闭，可按需启用。
- 对发言者昵称和消息内容做清洗，占位符单遍替换，降低二阶提示词注入风险。
- 提供 `/owner_auth_status` 状态命令，便于排查是否命中用户。

## 安装

1. 将本插件目录放入 MaiBot 的 `plugins/` 目录。
2. 重启 MaiBot 或重载插件。
3. 首次加载后打开 WebUI 插件配置页，或编辑生成的 `config.toml`。
4. 在「用户」页填写至少一个用户 QQ 号。

未配置任何有效用户 QQ 时，插件保持静默，不会对任何人注入提示词。

## 配置结构

新版配置分为三个区域：

- `plugin`：插件总开关、用户数量控制、日志等级、缓存有效期、planner 注入开关。
- `user1` ~ `userN`：用户槽位，数量由 `plugin.user_count` 控制。
- `non_owner`：非用户安全提醒开关和模板。

### 用户数量控制

`plugin.user_count` 决定生成多少个用户槽位。调大后需要保存并禁用再启用插件，或重启 MaiBot，新的槽位才会出现在配置模型中。

调小后，超出数量的用户槽位会在插件重载时清空。只是临时停用某个用户时，请关闭该用户槽位的「启用此用户」，不要调小用户数量。

### 用户槽位

每个用户槽位支持：

- `enabled`：是否启用此用户。
- `qq`：用户 QQ 号，身份验证唯一凭据。
- `nickname`：模板中显示的用户称呼。
- `group_id`：限制群聊群号，留空表示全局生效。
- `prompt_template`：命中该用户时注入的提示词模板。

如果同一个 QQ 同时配置了全局槽位和某群专属槽位，在对应群里会优先命中群专属槽位。

### 非用户提醒

`non_owner.enable_non_owner_inject` 默认关闭。开启后，非用户发言也会注入安全提醒，适合强防冒充场景，但可能让麦麦对普通群友显得过于警惕，并增加 token 消耗。

## 占位符

用户模板支持：

- `{nickname}` / `{owner_nickname}`：配置中的用户昵称。
- `{display_name}` / `{user}`：发言者聊天显示名。
- `{qq}` / `{owner_qq}` / `{user_qq}`：发言者 QQ。
- `{msg}` / `{message}`：本次消息文本。
- `{owner_names}`：已配置用户昵称列表。

非用户模板支持同样的显示名、QQ、消息和 `{owner_names}` 占位符。

未知占位符会原样保留，不会导致插件报错。

## 工作原理

插件使用官方 Hook，不再使用 monkey-patch：

- `chat.receive.after_process`：缓存当前会话最近一位真人发言者。
- `maisaka.replyer.before_request`：回复前定位发言者并注入身份提示词。
- `maisaka.planner.before_request`：可选，行动规划前注入身份提示词。

发言者定位顺序：

1. 通过 `reply_message_id` 精确获取被回复的消息。
2. 如果取不到，再使用本插件按 `session_id` 缓存的最近真人发言者。

插件刻意不使用“会话最近消息”作为兜底，避免群聊中把身份误判成另一个刚发言的人。

## 从 2.0.x 升级

本 fork 的 `2.0.x` 使用过如下配置：

```toml
[owner_auth]
enable_auth = true

[[owner_auth.users]]
nickname = "用户"
owner_qq = 123456789
prompt_template = "..."
```

升级到 `2.1.0` 后，插件会自动迁移到新的 `user1`、`user2` 固定槽位结构，并保留已有 QQ、昵称和模板。

建议升级前备份 `config.toml`。迁移完成后，旧的 `owner_auth` 结构会被新结构取代。

## 状态命令

在聊天中发送：

```text
/owner_auth_status
```

也可以发送：

```text
身份验证状态
主人验证状态
```

命令会返回插件启用状态、生效用户数、当前 QQ 是否命中、缓存数量和最近一次注入来源。

## 与原插件的关系

本仓库不是原插件的替代发行版。它只是我在原插件尚未更新新版 SDK 时做的自用分支。

现在原插件已经完成 MaiBot 1.0 / maibot_sdk 2.x 适配，并且维护入口更集中，普通用户建议直接使用：

<https://github.com/khiqwq/owner_auth_plugin>

## 许可

GPL-3.0-or-later。原作者与主要设计来自 [khiqwq/owner_auth_plugin](https://github.com/khiqwq/owner_auth_plugin)。
