# MaiIdentity API v1

SDK 路由为 `davidblackcn.maibot-maiidentity-plugin.<method>`，使用 `ctx.api.call(route, version="1", **payload)`。公开接口不证明调用者或实际消息作者身份。

| 方法 | 当前行为 |
| --- | --- |
| get_contract | 版本、运行状态及功能描述，不含账号或固定身份名单 |
| get_vita_policy | 查询指定账号在指定会话的 Vita 管理规则，返回布尔结果 |
| get_public_social_context | 返回中性群上下文，供 Coordinate 使用，不查询或暴露固定身份名单 |
| is_admin | 查询指定账号是否在当前配置的管理员名单中，返回布尔结果 |

没有开放名单、绑定、用户关系或委托的写 API。调用参数中的 is_owner、verified、caller_plugin_id、proof_ref 不能获得权限。

## 管理员查询

`is_admin` 必须且只能传入 account_id、bot_account_id、route_scope、stream_id，返回 `{"is_admin": true}` 或 `{"is_admin": false}`。按 Host 实际会话核对机器人账号与 scope，再读取 `management.admin_accounts`；机器人自身、无效参数、未就绪、配置在查询期间变更或查询失败均返回 false。

这只是配置查询，不证明调用方传入的账号就是发令者。执行插件须在自己的正式命令入口核对消息作者。接口不返回完整名单、不创建授权凭据，也不能直接执行管理动作。当前 Hush 使用自己的配置。

## Vita 管理规则

`get_vita_policy` 必须且只能传入 account_id、bot_account_id、route_scope、stream_id、action。action 支持 wake、enqueue_replan、start_sleep、start_activity、end_activity、apply_plan_patch、manage_goal。

Host 路由必须与 bot_account_id、route_scope 一致。配置中的空 scope 对应请求中的 null。返回 `{"policy_version": 1, "allowed": false}`，允许时为 true，失败统一拒绝。

Vita 必须从自己的官方 Command 上下文核对真实发令者；查询结果不是可转交的执行令牌。固定身份配置不参与该查询。权限直接来自 `management.admin_accounts`，没有数据库中的角色、委托或单独授权记录。

## Coordinate 群上下文

`get_public_social_context` 必须且只能传入 stream_id、bot_account_id、route_scope，并通过相同路由核对。

返回 envelope：api_version、ok、data、error、request_id、as_of。data 包含 stream_id、counts、relation_state、completeness、style、rule、revision。当前 counts 的 friend／family／partner 均为 0，relation_state 为 none_confirmed，style 为 neutral。它不代表现实中无人相识，也不能用来推断固定名单关系。

不可用时返回 CONTEXT_UNAVAILABLE。结果不含账号、称呼、个人提示词或旧用户关系记录。

## 聊天上下文

Replyer 根据准确的被回复消息作者匹配固定配置；群专属条目优先，昵称不作为匹配依据。上下文使用自然语言，区分已配置、当前会话未配置、对象未知。个人说明可被长度预算截短，身份与来源规则保留。

Planner 没有准确回复对象时仅提供通用来源规则。只处理已支持的 Hook 参数和 schema 1 items，不改写 Host 消息历史。每次替换本实例签名验证成功的旧提示，保留其他插件内容。标记签名仅用于识别自身文本，不是授权凭据。
