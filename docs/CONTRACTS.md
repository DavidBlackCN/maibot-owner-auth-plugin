# 插件协作边界

支持 Host／SDK 精确配对：1.3.12／2.15.0、1.3.15／2.16.0、1.3.18／2.19.0。运行版本由 get_contract 报告。

## MaiVita

Vita 从自己的官方 Command 入口核对消息作者，再调用 get_vita_policy 查询管理规则。固定身份称呼、模型输出、昵称和其他客户端传入的身份声明都不能代替这个过程。具体参数见 [API](API.md)。

## MaiCoordinate

get_public_social_context 保留群上下文结构，但不再统计用户之间的关系。返回中性结果，不披露固定身份名单，也不根据称呼推断亲密程度。Coordinate 不应将此结果当成账号认证或发送许可。

## MaiHush

Hush 继续使用自己配置的管理名单。MaiIdentity 不替它放行静音命令，也不提供绕过发送守卫的回执。

## 通用接口

不开放跨插件特权委托、远程角色管理或名单写接口。公开 API 可被访问，不代表调用者已获业务授权；拒绝响应不能被替换成默认允许。

## 配置维护

固定名单以安装实例的 `config.toml` 中 `identity.people` 为唯一来源，通过 WebUI 或文件编辑维护。插件接收 Runner 的配置更新，不自行写配置文件，也不提供消息写入命令。

当前支持的三个 Host 版本中，`component.update_plugin_config` 只允许内置插件管理器调用；在 Manifest 中声明该能力也不能使普通插件获得写入权限。SDK 的 `set_plugin_config()` 仅设置内存配置，不是持久化接口。
