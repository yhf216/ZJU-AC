# ZJU-AC

浙江大学「学在浙大」签到提醒工具。第一阶段提供终端输入学号密码、浏览器正常登录、轮询待签到活动、终端及桌面提醒。检测到签到后，请在畅课或学在浙大中完成签到。

这是独立实现的 Python 项目，后续逐步扩展。当前不提交签到，也不获取数字签到码、同学名单或模拟定位。

## 快速开始（Windows / PowerShell）

当前工作目录已创建 Python 3.12 conda 环境 `.conda`，直接运行：

```powershell
cd 'D:\Personal Documents\ZJU-AC'
.\.conda\python.exe -m zju_ac
```

按提示输入学号及统一身份认证密码；密码不会回显。程序默认打开 Microsoft Edge，尝试填写认证表单。遇到验证码、二次验证或表单变化时，在打开的浏览器中完成操作。登录成功后，每 15 秒查询一次签到；首次检测到待签到时提醒。浏览器需保持打开，按 `Ctrl+C` 退出并关闭本次会话。

密码和 Cookie 仅保留在当前进程的内存会话中，不写入配置或日志，不复用个人浏览器配置。每次启动需要重新登录。不应通过命令行参数、聊天或 Git 提供密码。

## 从零安装

```powershell
conda env create -f environment.yml --prefix .\.conda
.\.conda\python.exe -m pip install -e .
.\.conda\python.exe -m zju_ac
```

如果当前终端找不到 `conda`，可用 `& D:\miniconda3\Scripts\conda.exe` 替代命令中的 `conda`。也可采用标准虚拟环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m zju_ac
```

默认使用本机 Edge，无需下载额外浏览器。Linux、macOS 或未安装 Edge 的环境：

```text
python -m playwright install chromium
python -m zju_ac --browser chromium
```

## 常用命令

```powershell
# 离线演示通知，不登录、不访问网络
.\.conda\python.exe -m zju_ac --demo

# 每 20 秒查询；未完成时每 60 秒重复提醒
.\.conda\python.exe -m zju_ac --interval 20 --remind-every 60

# 登录后只查询一次，用于确认接口
.\.conda\python.exe -m zju_ac --once

# 仅输出终端提醒
.\.conda\python.exe -m zju_ac --no-desktop --no-bell

# 参数说明
.\.conda\python.exe -m zju_ac --help
```

默认每项活动在本次运行中只提醒一次；重启后重新提醒。指定 `--remind-every` 可重复提醒，轮询及重复提醒间隔至少 5 秒。程序每 5 分钟输出监控状态；网络暂时失败时指数退避，最多等待 300 秒。会话过期、权限错误和未知接口结构会明确报错，不把失败解释为“没有签到”。

桌面通知受 Windows 通知设置、专注模式及系统支持影响；终端输出始终保留。桌面通知是补充渠道，建议保持终端可见。系统休眠、程序关闭或断网期间无法实时提醒。

## 当前协议与验证边界

- 登录入口：`https://courses.zju.edu.cn/user/index`，通过 `/api/profile` 确认登录成功。
- 待签到入口：`GET /api/radar/rollcalls`。已有浙大项目中该接口返回活动级 `rollcall_status`、本人 `status`、`course_title` 及 `rollcall_id`，因此首版采用它作为候选协议。
- GPS、数字、二维码及其他类型统一提醒；实际覆盖范围取决于该接口向当前学生返回的活动。尚不能保证全部签到类型均被平台通过此接口下发。
- 已签、请假、尚未开始、活动结束、过期和超过截止时间的记录不提醒；无法识别的活动状态会报错，便于及时发现协议变化。
- 自动填写凭据只允许 HTTPS 下的 `identity.zju.edu.cn`、`zjuam.zju.edu.cn`、`courses.zju.edu.cn`。

**本版本完成离线自动测试及本机浏览器模拟表单检查，尚未使用真实浙大学生账号验证登录及正在进行的签到。** 当前执行环境访问浙大站点出现 TLS/超时错误；第一次实际运行需要核对认证表单及接口响应。若登录后接口结构不同，请提供去除账号、Cookie、ticket 和个人信息后的字段样例，便于继续适配。

参考依据：[浙大官方登录说明](https://zuits.zju.edu.cn/90694/list.htm)、[浙大接口调用实例](https://github.com/5dbwat4/ZJU-live-better/blob/main/courses.zju/autosign.js)。早期审查过 [XMU-AC](https://github.com/spicysuimai/XMU-AC)，未将其源码放入本项目。

## 项目结构

```text
zju_ac/
  auth.py       浏览器认证与凭据填写
  client.py     只读 API、会话及错误处理
  models.py     活动解析与状态判断
  monitor.py    轮询、去重、重复提醒和退避
  notify.py     终端与桌面通知
  cli.py        终端入口
tests/          离线单元测试
tools/          本机浏览器模拟检查
```

## 开发与检查

所有源文件及中文文档均为 UTF-8。新增功能独立分层实现；提交前运行格式、静态检查及离线测试；Git 提交使用简洁英文。

```powershell
.\.conda\python.exe -m pip install -r requirements-dev.txt
.\.conda\python.exe -m ruff check .
.\.conda\python.exe -m ruff format --check .
.\.conda\python.exe -m pytest -q

# 可选：需要本机 Edge；页面全部拦截并在本地模拟，无需账号
.\.conda\python.exe -m tools.smoke_browser
```

当前 66 项离线测试通过，覆盖活动与本人状态区分、截止时间、未知结构、HTTP/业务错误、会话失效、提醒去重、退避、凭据填写域名约束，以及登录超时和退出清理。真实认证、桌面通知显示和现场签到发现需要用户在本机实际验证。
