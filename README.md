# MaiIdentity

为 MaiBot 提供 QQ 账号登记、用户关系和 MaiVita 管理员设置。

- 登记自己的账号，让角色在聊天中参考身份与关系信息。
- 与其他已登记用户建立朋友、家人或伴侣关系，须双方确认，可随时撤销。
- 指定谁可以使用 MaiVita 的管理命令；关系称谓不会赋予管理权限。

当前版本 **3.2.3**。支持以下 MaiBot／Plugin SDK 组合：**1.3.18／2.19.0**、**1.3.15／2.16.0**、**1.3.12／2.15.0**。

## 安装与开始使用

1. 将插件放入 `MaiBot/plugins/maibot-maiIdentity-plugin/`，目录内应直接包含 `plugin.py`、`_manifest.json` 和 `maiidentity/`。
2. 启动 MaiBot，插件会生成默认配置。同一插件只安装一份，不要与旧 Owner Auth 同时启用。
3. 发送 `/maiidentity 登记我`。其他用户也登记后，就可以提出关系邀请。

默认配置可用于 Host 未设置 scope 的 QQ 会话。如果适配器设置了 scope，需要将 `identity.route_scope` 改为相同值；留空只匹配未设置 scope 的会话。

## 常用配置

如需管理 MaiVita，在生成的 `config.toml` 中填写管理员 QQ，保存后重载插件：

```toml
[management]
vita_admin_accounts = ["123456789"]
```

将示例号码换成自己的 QQ。留空表示无人拥有 Vita 管理权限，最多设置 16 人。此名单不控制 MaiHush 的群静音权限。

身份与关系信息默认会加入聊天上下文。如需关闭：

```toml
[context]
enabled = false
```

其他设置通常保持默认即可，完整说明见 [配置示例](config.example.toml)。

## 命令

| 命令 | 用途 |
| --- | --- |
| `/maiidentity help` | 查看帮助 |
| `/maiidentity 登记我` | 登记发送命令的 QQ 账号，也可用 `register` |
| `/maiidentity 建立关系 对方QQ 朋友` | 提出关系邀请，也支持“家人”“伴侣” |
| `/maiidentity 确认关系 关系ID` | 接受对方邀请，有效期为 24 小时 |
| `/maiidentity 查看关系` | 查看自己可见的关系 |
| `/maiidentity 撤销关系 关系ID` | 撤销关系，双方均可操作 |
| `/maiidentity_status` | 查看插件状态 |

将“对方QQ”和“关系ID”替换为实际值。关系指用户之间的关系，不是用户与机器人的关系。

## 常见问题

**登记或邀请失败？** 确认会话的 scope 与配置一致；建立关系需要双方先登记，邀请必须由对方本人确认。

**登记后仍不能管理 Vita？** 登记、关系与管理员权限是独立的。检查 `management.vita_admin_accounts`，保存后重载。

**命令没有回复？** 回复也受 MaiVita 睡眠和 MaiHush 静音限制，可先检查插件日志。

本插件根据消息来源识别 QQ 账号，不提供实名认证，也不会根据聊天中的自称更换身份。私密关系不会出现在公开群摘要中。

## 相关资料

- [版本变化](UPDATE_NOTES.md)
- [插件接口](docs/API.md)
- [使用限制](docs/LIMITATIONS.md)
- [项目仓库](https://github.com/DavidBlackCN/maibot-maiidentity-plugin)

感谢 MaiBot、插件 SDK、[原 Owner Auth 插件](https://github.com/khiqwq/owner_auth_plugin)、风花叶和 DavidBlackCN。详见 [来源说明](docs/SOURCES.md)。

许可证：[GPL-3.0-or-later](LICENSE)。
