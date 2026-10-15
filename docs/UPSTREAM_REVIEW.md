# 畅课签到上游审查记录

审查日期：2026-10-15（Asia/Shanghai）。读取了两个指定仓库的开放/关闭 issue 与 PR 索引，并重点检查签到相关正文、评论、当前实现及引用链。网页搜索快照可能滞后；存在冲突时以本轮直接读取的 GitHub API 当前代码和最新讨论为依据。没有登录第三方服务或向真实活动提交签到。

## 已确认的关键变化

| 主题 | 依据 | 本项目处理 |
| --- | --- | --- |
| GPS 范围外不再返回距离 | [alkali210 的 10 月 12 日公告](https://github.com/alkali210/XMU-Rollcall-Bot)、[KrsMt #35](https://github.com/KrsMt-0113/XMU-Rollcall-Bot/issues/35) | 删除距离采集、三点拟合及探测请求；只提交配置选定的坐标 |
| 空定位包不再可靠 | [KrsMt #35 中的更新讨论](https://github.com/KrsMt-0113/XMU-Rollcall-Bot/issues/35#issuecomment-6138569232)，引用 [THU #6](https://github.com/hot-YUser/auto-rollcall-thu-tronclass/issues/6) | 不发送空定位包，不将历史捷径作为后备策略 |
| 数字详情接口可能返回空码 | [ZJU-live-better #36](https://github.com/5dbwat4/ZJU-live-better/issues/36)、[THU 的停维护公告](https://github.com/hot-YUser/auto-rollcall-thu-tronclass) | 保留双通道及缺码处理，不假定旧接口继续提供数字码 |
| 新的课表取码路径 | [alkali210 PR #13](https://github.com/alkali210/XMU-Rollcall-Bot/pull/13)、[KrsMt #35](https://github.com/KrsMt-0113/XMU-Rollcall-Bot/issues/35) | 现有 `/api/timetable_rollcalls` 通道按课程、日期、活动编号匹配 |
| 早八取码的时区错误 | [alkali210 #16 及修复说明](https://github.com/alkali210/XMU-Rollcall-Bot/issues/16) | 已使用 UTC 活动日期，保留跨日回归测试；不照搬旧北京时间实现 |
| 高频尝试会限流 | [ZJU-live-better #36 的实测讨论](https://github.com/5dbwat4/ZJU-live-better/issues/36) | 不爆破、枚举、换会话尝试；每个工作进程内每项活动最多一次写入，429 后仅核验结果 |
| 非 JSON/SSO 页面导致轮询失败 | [ZJU-live-better #2](https://github.com/5dbwat4/ZJU-live-better/issues/2)、[PR #1](https://github.com/5dbwat4/ZJU-live-better/pull/1)、[login-ZJU #1](https://github.com/5dbwat4/login-ZJU/issues/1) | 继续检查响应类型与登录会话，使用看门狗恢复，日志不打印 HTML 或票据 |
| 无请求超时导致界面存活却卡死 | [KrsMt #33](https://github.com/KrsMt-0113/XMU-Rollcall-Bot/issues/33)、[dangzitou 的 monitor.py](https://github.com/dangzitou/xmu-rollcall-bot-new/blob/main/xmu-rollcall-cli/xmu_rollcall/monitor.py) | 保留现有 15 秒单次请求超时与读请求退避，不复制写请求重试 |
| 二维码与其他点名不能等同数字/GPS | [ZJU-live-better #15](https://github.com/5dbwat4/ZJU-live-better/issues/15)、[#20](https://github.com/5dbwat4/ZJU-live-better/issues/20) | 二维码及其他类型只提醒，提交前重新确认类型 |

这些是公开项目和参与者的观察，不代表所有学校同时部署同一版本；尤其不将历史的具体提交次数限制、半径或脚本成功率当作当前浙大的固定保证。

## 仓库与引用链

- [alkali210/XMU-Rollcall-Bot](https://github.com/alkali210/XMU-Rollcall-Bot)：重点检查 README、数字取码实现、签到处理、#16 的 UTC 修复、#13 的新接口迁移及相关网络恢复 PR。其最新主分支取消常规 GPS 自动处理，提供已知坐标提交命令。
- [5dbwat4/ZJU-live-better](https://github.com/5dbwat4/ZJU-live-better)：检查 `courses.zju/autosign.js` 中的参考坐标和请求形状，以及签到相关 #2/#12/#14/#15/#20/#36、PR #10/#11/#25/#26 等讨论。主脚本仍可见距离拟合和“无频率限制”的旧注释；后续 issue 已报告变化，因此不照搬这些假设。
- [KrsMt-0113/XMU-Rollcall-Bot](https://github.com/KrsMt-0113/XMU-Rollcall-Bot)：alkali210 的上游；重点沿 #35 跟踪新取码接口、GPS 距离消失、其他实现失效及 fork 维护情况，并查看 #22/#9/#30/#33 等相关信息。
- [hot-YUser/auto-rollcall-thu-tronclass](https://github.com/hot-YUser/auto-rollcall-thu-tronclass)：由 KrsMt #35 引用；检查 README 和 #6。README 的 9 月公告中部分 GPS 描述比 10 月更新更早，不能据此认定当前兼容；#6 是雷达失败报告，API 中没有后续评论。没有将它的自动爆破、教师辅助或 QR 取码研究引入本项目。
- [silvercow002/tronclass-script](https://github.com/silvercow002/tronclass-script)：THU 项目的历史上游，查看 README、配置和基本签到功能说明，作为引用链背景；没有从其功能列表推断当前接口有效。
- [dangzitou/xmu-rollcall-bot-new](https://github.com/dangzitou/xmu-rollcall-bot-new)：KrsMt #33 链接的超时处理参考；当前轮询实现设定 30 秒超时及有限读重试。本项目已具备超时和退避，保留自己的实现。
- [5dbwat4/login-ZJU](https://github.com/5dbwat4/login-ZJU)：ZJU-live-better 的认证依赖，检查 README 与 SSO 相关 issue；本项目继续独立实现 CAS/Keycloak 登录和会话识别。
- [YixuAnsensei/xmu_rollcall_zako_Tronclass](https://github.com/YixuAnsensei/xmu_rollcall_zako_Tronclass)：由 ZJU PR #25 引用，本轮公共页面和 API 返回 404，无法审查当前源码。只记录其历史引用关系，不声称已读到或验证其当前方案。

上游还包含课程素材、作业、视频、成绩等功能，本轮审查和实现聚焦签到、认证、网络恢复与配置。未把任何参考仓库克隆或复制进 ZJU-AC；仅将用户要求的公开地点参考数值放入配置，并保留来源注释。

## 当前实现边界

根目录 `config.toml` 统一控制运行模式、提醒、看门狗、自动开关、门控及 GPS 地点。按后续需求，自动模式和人数门控现已默认开启：已签严格超过 1/4 或超过 20 人时放行；名单不可用、等待达到 120 秒或剩余不超过 30 秒时保底放行。所有数值及查询间隔均可配置，手动模式不等待人数门控。

GPS 只提交选定地点一次。没有学生端读取当前教师签到中心的已验证路径，因此没有虚构这种接口；参考点按实际课堂修改。自动取不到数字码时仅提醒，手动模式仍可补码。所有成功结果均以本人签到状态回查为准，真实活动兼容性仍需现场验证。
