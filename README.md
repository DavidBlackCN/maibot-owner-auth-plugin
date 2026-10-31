# MaiIdentity

让 MaiBot 按 QQ 认出熟悉的人，使用你设置的称呼和相处方式，并为 MaiVita 提供管理员权限查询。

当前版本 **3.4.0**。支持 MaiBot／Plugin SDK 组合：**1.3.18／2.19.0**、**1.3.15／2.16.0**、**1.3.12／2.15.0**。

## 安装

将插件放入 `MaiBot/plugins/maibot-maiIdentity-plugin/`，目录内应直接包含 `plugin.py`、`_manifest.json` 和 `maiidentity/`。启动后会生成配置文件。同一插件只安装一份，不要与 Owner Auth 同时启用。

## 设置固定身份

在 WebUI 的身份配置中增删、修改名单，或直接编辑 `config.toml`。插件不提供消息命令修改名单。配置示例：

```toml
[[identity.people]]
qq = "123456789"
nickname = "妈妈"
prompt_template = "与{nickname}自然亲近，可以撒娇，关心点到为止。"
group_id = ""
enabled = true
```

替换示例 QQ。只需填写 `qq` 和 `nickname`，其他字段可省略：

- `prompt_template`：个人相处说明，留空时使用默认表达；可用 `{nickname}` 引用称呼。
- `group_id`：留空适用于群聊和私聊；填写群号则只在该群生效。
- `enabled`：设为 `false` 暂停使用此条，保留内容。

同一 QQ 可以分别设置全局和群专属身份，群专属设置优先。同一 QQ、同一适用范围不能重复。停用群专属设置后，如有全局设置则使用全局设置。通过 Host 保存名单后生效；直接编辑文件后重载插件。无需发送登记或关系确认命令。

身份按消息作者账号匹配。改昵称不会改变配置身份，其他人使用“麦麦的妈妈”“麦麦的情侣”等群昵称，也不会命中你的设置。插件会提示模型区分昵称与固定身份，但模型的实际表达仍可能有偏差。

## 管理员

```toml
[management]
admin_accounts = ["123456789"]
```

填写有权使用 Vita 管理命令的 QQ。WebUI 保存后生效；直接编辑文件后重载。留空表示无人获权，最多 16 人。固定称呼不产生管理权限，此名单也不控制 MaiHush 的群静音权限。

其他设置通常保持默认即可，完整说明见 [配置示例](config.example.toml)。

## 命令与排错

- `/maiidentity help`：查看帮助。
- `/maiidentity status` 或 `/maiidentity_status`：查看是否就绪及启用的身份条目数。

**没有使用配置称呼？** 检查 QQ、启用开关和适用群。若适配器设置了 scope，`identity.route_scope` 须填写相同值；默认留空只匹配 Host 未设置 scope 的会话。无法准确确定回复对象时，插件不会猜测身份。

**命令没有回复？** 回复也受 MaiVita 睡眠和 MaiHush 静音限制，可查看 MaiBot 日志。

**需要关闭身份提示？** 将 `context.enabled` 设为 `false` 并重载插件。

## 相关资料

[版本变化](UPDATE_NOTES.md) · [插件接口](docs/API.md) · [使用限制](docs/LIMITATIONS.md) · [项目仓库](https://github.com/DavidBlackCN/maibot-maiidentity-plugin)

感谢 MaiBot、插件 SDK、[原 Owner Auth 插件](https://github.com/khiqwq/owner_auth_plugin)、风花叶和 DavidBlackCN。详见 [来源说明](docs/SOURCES.md)。

许可证：[GPL-3.0-or-later](LICENSE)。
