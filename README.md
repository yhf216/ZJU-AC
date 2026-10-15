# ZJU-AC

浙江大学「学在浙大」签到提醒与数字签到工具。终端输入学号密码，通过纯 HTTP 完成统一身份认证并轮询待签到活动，提供终端及桌面提醒。数字签到由用户在终端确认后提交；整个程序无需安装、启动或保持浏览器。

这是独立实现的 Python 项目，后续逐步扩展。GPS、二维码及其他类型目前仅提醒，需在正常客户端完成。

## 快速开始（Windows / PowerShell）

先安装 Miniconda 或 Anaconda，在支持 conda 的终端中执行：

```powershell
cd 'D:\Personal Documents\ZJU-AC'
conda create -n zju-ac python=3.12 pip -y
conda activate zju-ac
python -m pip install -r requirements.txt
python -m zju_ac
```

按提示输入学号及统一身份认证密码；密码不会回显。程序跟随课程站的认证跳转，读取动态表单并通过 HTTPS 提交。登录成功后，每 15 秒查询一次签到；首次检测到待签到时提醒，数字签到还会在终端询问是否提交。按 `Ctrl+C` 退出并清理本次会话。

密码和 Cookie 仅保留在当前进程的内存会话中，不写入配置或日志。每次启动需要重新登录。不应通过命令行参数、聊天或 Git 提供密码。

环境由 conda 管理，存放在 conda 的环境目录中；项目目录只保留源码、文档和依赖声明。后续启动无需重新安装：

```powershell
conda activate zju-ac
cd 'D:\Personal Documents\ZJU-AC'
python -m zju_ac
```

如果终端找不到 `conda`，请使用安装时提供的 Anaconda Prompt，或在其中运行 `conda init powershell` 后重新打开 PowerShell。

从旧版升级时，在已有环境中更新依赖即可；新版本不再使用 Playwright，也不提供 `--browser` 参数：

```text
conda activate zju-ac
python -m pip install -r requirements.txt
```

新版新增 `requests` 和 `beautifulsoup4` 依赖。程序会在请求学号密码前检查认证模块能否加载；缺少依赖时会提示安装命令及当前 Python 路径。请在运行程序的同一环境中执行安装命令。

## 常用命令

```powershell
# 离线演示通知，不登录、不访问网络
python -m zju_ac --demo

# 每 20 秒查询；未完成时每 60 秒重复提醒
python -m zju_ac --interval 20 --remind-every 60

# 登录后只查询一次，不询问或提交签到
python -m zju_ac --once

# 持续监控，但仅提醒，不询问或提交签到
python -m zju_ac --reminders-only

# 仅输出终端提醒
python -m zju_ac --no-desktop --no-bell

# 参数说明
python -m zju_ac --help
```

默认每项活动在本次运行中只提醒一次；重启后重新提醒。指定 `--remind-every` 可重复提醒，轮询及重复提醒间隔至少 5 秒。程序每 5 分钟输出监控状态；网络暂时失败时指数退避，最多等待 300 秒。会话过期、权限错误和未知接口结构会明确报错，不把失败解释为“没有签到”。

桌面通知受 Windows 通知设置、专注模式及系统支持影响；终端输出始终保留。桌面通知是补充渠道，建议保持终端可见。系统休眠、程序关闭或断网期间无法实时提醒。

## 数字签到

默认运行 `python -m zju_ac` 时，检测到数字签到会先发出提醒，再显示：

```text
确认提交《测试课程》课堂签到（编号 42）的数字签到？[y/N]：
```

- 输入 `y` 或 `yes` 后才会读取数字码并尝试提交；直接回车、输入 `n` 或其他内容均跳过。
- 自动读取顺序：点名详情接口的 `number_code`，随后尝试课表日期接口的同一活动记录，查询日期取活动时间的 UTC 日期。不缓存数字码，不枚举或猜测数字码。
- 接口未提供数字码时，终端会提示输入课堂公布的码（4–8 位 ASCII 数字，保留前导零）；直接回车取消。此步骤只会在你已确认该活动后出现。
- 同一活动在本次运行中只询问一次；跳过、取消或失败后不会反复弹出确认。需要再次尝试时，可重启程序或使用正常客户端。
- 等待终端输入期间继续轮询并提醒其他活动；有多项待确认时按顺序询问，每条提示包含课程、标题和活动编号。所有 HTTP 请求均在主线程执行，网络请求期间处理输入可能短暂延后。
- 提交前重新检查活动是否仍为同一课程的进行中数字签到，并核对本人状态；活动结束、本人已签/请假、缺少课程编号或无法取得本人记录时取消提交。
- 每次确认最多发送一次提交请求。提交后回查本人课程签到记录，只有 `on_call` / `on_call_fine` 才报告 `[签到成功]`，HTTP 200 本身不算成功。
- 网络超时或服务端错误导致结果不确定时，仅回查，不自动重发；显示 `[待核验]` 时请在畅课查看结果。关闭终端输入或退出程序会取消尚未执行的确认。

`--reminders-only`、`--once` 和 `--demo` 都不会提交签到。Windows 桌面通知用于提醒，确认操作在终端完成。

## 当前协议与验证边界

- 登录入口：`https://courses.zju.edu.cn/user/index`，通过 `/api/profile` 确认登录成功。
- 待签到入口：`GET /api/radar/rollcalls`。已有浙大项目中该接口返回活动级 `rollcall_status`、本人 `status`、`course_title` 及 `rollcall_id`，因此首版采用它作为候选协议。
- 数字提交：`PUT /api/rollcall/{id}/answer_number_rollcall`，携带 `deviceId` 和 `numberCode`；同一次运行使用稳定的设备标识。
- 结果确认：`GET /api/course/{course_id}/student/{student_id}/rollcalls`，按活动编号匹配本人的记录；最多查询 5 页、每页 100 条。数字码详情响应可能包含名单字段，程序不使用或保存这些字段，结果核验只查询本人记录。
- GPS、数字、二维码及其他类型统一提醒；实际覆盖范围取决于该接口向当前学生返回的活动。尚不能保证全部签到类型均被平台通过此接口下发。
- 已签、请假、尚未开始、活动结束、过期和超过截止时间的记录不提醒；无法识别的活动状态会报错，便于及时发现协议变化。
- 支持旧 CAS 的动态 `execution` 参数及 RSA 公钥加密，以及 `identity.zju.edu.cn` 的标准 Keycloak 用户名密码表单。依据实际跳转和表单识别协议，不固定认证提交地址或会话 token。
- 认证请求只允许 HTTPS 下的 `identity.zju.edu.cn`、`zjuam.zju.edu.cn`、`courses.zju.edu.cn`；保留证书验证，限制跳转次数，密码只提交一次。
- 标准 OTP/TOTP 二次验证可在终端输入动态验证码。图形验证码、滑块、扫码、JavaScript 加密的定制表单等验证方式尚未支持；遇到时明确退出，不会启动浏览器或尝试绕过验证。
- `--login-timeout` 设置认证流程的时间预算（默认 180 秒）；单次网络请求最多等待 15 秒。等待用户输入验证码时不强制中断输入，下一次请求前检查剩余时间。
- 默认遵循系统/环境代理设置；TLS 或网络错误时检查代理及校园网连接。程序不自动降低 TLS 安全设置或关闭证书验证。

用户已反馈网络问题修复。新增数字签到功能完成离线协议及交互测试，**尚未对真实浙大活动提交签到**；厦大的课表取码通道能否用于浙大，仍需实际验证。取不到数字码时可手动输入，不影响确认机制。若运行失败，请提供终端错误信息；如需协议样例，应先去除账号、Cookie、ticket、数字码和个人信息。

参考依据：[浙大官方登录说明](https://zuits.zju.edu.cn/90694/list.htm)、[浙大接口调用实例](https://github.com/5dbwat4/ZJU-live-better/blob/main/courses.zju/autosign.js)、[旧 CAS 协议参考](https://github.com/5dbwat4/login-ZJU/blob/main/src/zjuam.ts)、[XMU-AC 数字码接口参考](https://github.com/spicysuimai/XMU-AC/blob/master/auto_checkin.py)。项目独立实现，未放入厦大源码。

## 项目结构

```text
zju_ac/
  auth.py       纯 HTTP 认证、动态表单与安全跳转
  client.py     查询、数字提交、本人状态核验及错误处理
  checkin.py    终端确认队列、补码及提交流程
  models.py     活动解析与状态判断
  monitor.py    轮询、去重、重复提醒和退避
  notify.py     终端与桌面通知
  cli.py        终端入口
tests/          离线单元测试
```

## 开发与检查

所有源文件及中文文档均为 UTF-8。新增功能独立分层实现；提交前运行格式、静态检查及离线测试；Git 提交使用简洁英文。

```powershell
conda activate zju-ac
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
```

测试覆盖活动与本人状态区分、截止时间、未知结构、HTTP/业务错误、会话失效、提醒去重、退避、CAS/Keycloak 认证及启动依赖检查，也覆盖明确确认后才提交、默认跳过、手动补码、活动过期、结果回查、写请求不自动重试及输入不阻塞轮询。未处理异常只显示类型及代码位置，不输出可能包含密码或票据的异常原文。离线检查不需要浏览器或真实账号；实际签到仍需现场验证。
