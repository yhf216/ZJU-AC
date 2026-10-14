# ZJU-AC

浙江大学「学在浙大」签到提醒工具。终端输入学号密码，通过纯 HTTP 完成统一身份认证并轮询待签到活动，提供终端及桌面提醒。整个程序无需安装、启动或保持浏览器。检测到签到后，请在畅课或学在浙大中完成签到。

这是独立实现的 Python 项目，后续逐步扩展。当前不提交签到，也不获取数字签到码、同学名单或模拟定位。

## 快速开始（Windows / PowerShell）

先安装 Miniconda 或 Anaconda，在支持 conda 的终端中执行：

```powershell
cd 'D:\Personal Documents\ZJU-AC'
conda create -n zju-ac python=3.12 pip -y
conda activate zju-ac
python -m pip install -r requirements.txt
python -m zju_ac
```

按提示输入学号及统一身份认证密码；密码不会回显。程序跟随课程站的认证跳转，读取动态表单并通过 HTTPS 提交。登录成功后，每 15 秒查询一次签到；首次检测到待签到时提醒。按 `Ctrl+C` 退出并清理本次会话。

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

## 常用命令

```powershell
# 离线演示通知，不登录、不访问网络
python -m zju_ac --demo

# 每 20 秒查询；未完成时每 60 秒重复提醒
python -m zju_ac --interval 20 --remind-every 60

# 登录后只查询一次，用于确认接口
python -m zju_ac --once

# 仅输出终端提醒
python -m zju_ac --no-desktop --no-bell

# 参数说明
python -m zju_ac --help
```

默认每项活动在本次运行中只提醒一次；重启后重新提醒。指定 `--remind-every` 可重复提醒，轮询及重复提醒间隔至少 5 秒。程序每 5 分钟输出监控状态；网络暂时失败时指数退避，最多等待 300 秒。会话过期、权限错误和未知接口结构会明确报错，不把失败解释为“没有签到”。

桌面通知受 Windows 通知设置、专注模式及系统支持影响；终端输出始终保留。桌面通知是补充渠道，建议保持终端可见。系统休眠、程序关闭或断网期间无法实时提醒。

## 当前协议与验证边界

- 登录入口：`https://courses.zju.edu.cn/user/index`，通过 `/api/profile` 确认登录成功。
- 待签到入口：`GET /api/radar/rollcalls`。已有浙大项目中该接口返回活动级 `rollcall_status`、本人 `status`、`course_title` 及 `rollcall_id`，因此首版采用它作为候选协议。
- GPS、数字、二维码及其他类型统一提醒；实际覆盖范围取决于该接口向当前学生返回的活动。尚不能保证全部签到类型均被平台通过此接口下发。
- 已签、请假、尚未开始、活动结束、过期和超过截止时间的记录不提醒；无法识别的活动状态会报错，便于及时发现协议变化。
- 支持旧 CAS 的动态 `execution` 参数及 RSA 公钥加密，以及 `identity.zju.edu.cn` 的标准 Keycloak 用户名密码表单。依据实际跳转和表单识别协议，不固定认证提交地址或会话 token。
- 认证请求只允许 HTTPS 下的 `identity.zju.edu.cn`、`zjuam.zju.edu.cn`、`courses.zju.edu.cn`；保留证书验证，限制跳转次数，密码只提交一次。
- 标准 OTP/TOTP 二次验证可在终端输入动态验证码。图形验证码、滑块、扫码、JavaScript 加密的定制表单等验证方式尚未支持；遇到时明确退出，不会启动浏览器或尝试绕过验证。
- `--login-timeout` 设置认证流程的时间预算（默认 180 秒）；单次网络请求最多等待 15 秒。等待用户输入验证码时不强制中断输入，下一次请求前检查剩余时间。
- 默认遵循系统/环境代理设置；TLS 或网络错误时检查代理及校园网连接。程序不自动降低 TLS 安全设置或关闭证书验证。

**旧版浏览器登录已由用户测试通过；新版纯 HTTP 认证尚未使用真实账号完成验证。** 开发环境能获取旧 CAS 的公开登录表单，但访问课程站和新版认证站仍出现 TLS 连接错误。离线测试模拟了 CAS、Keycloak、动态验证码、服务跳转及登录态校验；实际认证表单或平台要求可能不同。若运行失败，请提供终端错误信息；如需协议样例，应先去除账号、Cookie、ticket 和个人信息。

参考依据：[浙大官方登录说明](https://zuits.zju.edu.cn/90694/list.htm)、[浙大接口调用实例](https://github.com/5dbwat4/ZJU-live-better/blob/main/courses.zju/autosign.js)、[旧 CAS 协议参考](https://github.com/5dbwat4/login-ZJU/blob/main/src/zjuam.ts)。早期审查过 [XMU-AC](https://github.com/spicysuimai/XMU-AC)，未将其源码放入本项目。

## 项目结构

```text
zju_ac/
  auth.py       纯 HTTP 认证、动态表单与安全跳转
  client.py     只读 API、会话及错误处理
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

当前 91 项离线测试通过，覆盖活动与本人状态区分、截止时间、未知结构、HTTP/业务错误、会话失效、提醒去重、退避，以及 CAS/Keycloak 认证、RSA 加密、域名约束、密码提交次数、动态验证码、登录超时和会话清理。离线检查不需要浏览器或真实账号。真实认证、桌面通知显示和现场签到发现需要用户在本机实际验证。
