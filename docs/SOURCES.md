# 来源与许可

MaiIdentity 基于 [DavidBlackCN/maibot-owner-auth-plugin](https://github.com/DavidBlackCN/maibot-maiIdentity-plugin) 的提交 `155df1ae0dbde4a8690efb2a082ed9c9c6ede40d` 演进，保留原 Git 历史、[GPL-3.0-or-later](../LICENSE)、[khiqwq/owner_auth_plugin](https://github.com/khiqwq/owner_auth_plugin)、风花叶与 DavidBlackCN 的署名。

分层和公开契约参考 [MaiVita](https://github.com/DavidBlackCN/maibot-maivita-plugin/tree/7ec8fa99b6a2745844913465142e86764167e427)；身份提示和管理查询实现独立维护，没有复制其 AGPL 生活引擎。

宿主接口与测试基线来自 [MaiBot](https://github.com/Mai-with-u/MaiBot) 和 [maibot-plugin-sdk](https://pypi.org/project/maibot-plugin-sdk/)。可复现版本及源码校验值保存在 `tests/fixtures/`；Host 源码、第三方依赖、运行配置和本地验收记录不随插件分发。版本变化见 [UPDATE_NOTES](../UPDATE_NOTES.md)。
