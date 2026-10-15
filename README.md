# ZJU-AC

浙江大学「学在浙大」签到提醒与签到工具。终端输入学号密码，通过纯 HTTP 登录、轮询并提供终端及 Windows 桌面提醒；数字和 GPS 签到支持手动确认或配置开启自动处理。无需安装、启动或保持浏览器。

运行参数统一放在根目录 [config.toml](config.toml)，修改后重启生效。默认手动确认、默认开启看门狗。GPS 使用配置中选定地点的坐标，已移除依赖服务端返回距离的探测和拟合算法。二维码及其他类型目前仅提醒。

## 安装与启动（Windows / PowerShell）

安装 Miniconda 或 Anaconda 后，在支持 conda 的终端执行：

```powershell
cd 'D:\Personal Documents\ZJU-AC'
conda create -n zju-ac python=3.12 pip -y
conda activate zju-ac
python -m pip install -r requirements.txt
python -m zju_ac
```

后续只需激活环境并启动：

```powershell
conda activate zju-ac
cd 'D:\Personal Documents\ZJU-AC'
python -m zju_ac
```

按提示输入学号和统一身份认证密码，密码隐藏输入；OTP/TOTP 验证码仍需交互输入。按 `Ctrl+C` 退出。如果找不到 conda，可使用 Anaconda Prompt，或在其中执行 `conda init powershell` 后重开终端。环境由 conda 管理，项目目录不放 conda 环境、依赖包或参考仓库的源码。

密码、Cookie 只在内存中保留，不写入配置或日志。看门狗父进程保留本次凭据供恢复登录；每次手动启动重新输入。不要把账号密码写入 `config.toml`。

## 配置

启动命令保持 `python -m zju_ac`。旧的 `--interval`、`--once`、`--demo`、`--reminders-only`、`--no-watchdog` 等运行参数已移除，统一编辑配置文件；命令行仅保留 `--help` 和 `--version`。程序按源码根目录定位配置，不受终端当前目录改变影响。缺失文件、无效 UTF-8/TOML、未知字段或错误类型会在询问凭据前报错。

| 配置项 | 默认值 | 含义 |
| --- | --- | --- |
| `runtime.mode` | `"monitor"` | `monitor` 正常监控处理；`reminders` 只提醒；`once` 只查询一次；`demo` 离线演示通知 |
| `runtime.interval` | `15` | 轮询间隔秒数，至少 5 |
| `runtime.remind_every` | `0` | 每项活动仅提醒一次；设为至少 5 时按秒重复提醒 |
| `runtime.login_timeout` | `180` | 登录时间预算秒数，至少 5 |
| `checkin.auto_checkin` | `false` | `false` 终端确认；`true` 自动处理数字和 GPS 活动 |
| `checkin.gate` | `"immediate"` | 自动签到门控，目前仅支持直接签到，后续根据需求扩展 |
| `notifications.desktop` / `bell` | `true` | 桌面通知 / 终端提示音 |
| `watchdog.enabled` | `true` | 独立进程看门狗 |
| `watchdog.restart_delay` | `15` | 异常退出后重启等待秒数，至少 1 |
| `watchdog.max_restarts` | `5` | 滚动 10 分钟内最多重启次数，至少 1 |
| `gps.location` | `"ZJGD1"` | 本次运行使用的 GPS 地点键，适用于所有 GPS 活动 |
| `gps.accuracy` | `35.0` | 接口精度字段，单位米，须大于 0、不超过 10000；并非真实测量精度 |
| `gps.locations.<地点键>` | 12 个参考点 | 地点名称、纬度、经度，可修改或新增 |

开启自动签到时修改现有配置节：

```toml
[checkin]
auto_checkin = true
gate = "immediate"
```

`auto_checkin = false` 恢复手动确认。当前门控默认直接签到；尚未实现人数、比例、延迟等条件，填写其他门控值会报错。门控入口独立在 `zju_ac/gate.py`；之后补充条件不会影响终端确认和网络层。

需要只提醒时，将 `runtime.mode` 改为 `"reminders"`；单次查询改为 `"once"`；离线通知测试改为 `"demo"`。这三个模式均不会提交签到，即使自动开关开启。自动模式的登录和额外身份验证仍需终端输入。

每次轮询成功输出“监控正常”及待签到数量。网络暂时失败时指数退避，最多等待 300 秒；会话失效、权限问题和未知活动结构明确报错，不当成“没有签到”。桌面提醒受 Windows 通知设置、专注模式和系统支持影响，终端输出始终保留。休眠、断网或程序关闭期间不能实时提醒。

## 手动与自动签到

手动模式下，检测到数字或 GPS 活动后，先提醒，再询问是否提交。输入 `y` / `yes` 并按回车继续；回车、`n` 或其他内容均跳过。程序运行期间仍能接收键盘输入，只是不能同时执行 PowerShell 命令；出现新轮询日志时，原来的输入提示仍在等待这一行。Windows 看门狗子进程会显式恢复控制台输入，避免空设备被误判为可交互终端。

自动模式下，活动通过门控后进入自动队列，不询问 `y/N`。所有 HTTP 请求仍在监控主线程执行；手动模式等待输入时继续轮询，网络请求期间处理输入可能短暂延后。数字与 GPS 共用输入队列，各项决定按活动编号区分。

两个模式共用提交检查：活动必须仍在进行、课程和类型匹配，本人状态必须明确为 `absent`。已签、请假、活动结束或本人记录无法确认时取消。每个工作进程内每项活动最多尝试一次，不反复消耗提交机会；失败后可用正常客户端处理。

提交后只查询本人课程签到记录，只有 `on_call` / `on_call_fine` 才显示 `[签到成功]`。HTTP 200 本身不算成功。超时、限流、服务端错误或无法解析写响应时只回查，不自动重发；显示 `[待核验]` 时请在畅课检查结果。

### 数字签到

保留双通道取码：先查点名详情的 `number_code`，缺码、无权限或暂时失败时查询课表日期接口的同一活动。课表日期取活动开始时间的 **UTC 日期**，避免北京时间早八被查到错误日期。不缓存、枚举或猜测数字码，日志不输出实际数字码。

两通道均无法取码时，手动模式继续提示输入课堂公布的 4–8 位 ASCII 数字码，保留前导零，回车取消；自动模式仅提醒，不提交，也不会转入等待终端补码。会话失效仍触发现有恢复流程。

### GPS 签到

GPS 方法已改为提交已知坐标，**不依赖范围外响应包含 `distance`**。根目录配置已按 [ZJU-live-better 的参考点](https://github.com/5dbwat4/ZJU-live-better/blob/main/courses.zju/autosign.js)填入紫金港、玉泉、之江、华家池共 12 个地点。注释注明来源、经纬度顺序及按实际地点修改的要求。

例如使用玉泉教四，修改现有 `[gps]` 中的 `location = "YQ4"`。也可新增实际地点并选中：

```toml
# 修改现有 [gps] 节，不要重复添加同名节：
# location = "my_classroom"

[gps.locations.my_classroom]
name = "我的实际上课地点"
latitude = 30.261555
longitude = 120.122176
```

示例坐标不是本机真实位置，也不是从教师账号读取的签到中心；请根据实际需要核对和修改。所有 GPS 活动使用本次启动选定的同一地点，跨校区或更换地点后需改配置并重启。未选地点（`location = ""`）时 GPS 仅提醒。

每项 GPS 活动只向所选坐标发送一次定位请求，携带稳定设备标识和配置精度；不遍历地点、不发送空定位包、不反推距离。范围外拒绝即使没有距离字段，也会明确提示检查配置并停止；不会自动换地点。日志不输出坐标、距离或原始响应。

已完成离线协议、交互和自动流程验证，尚未在真实浙大 GPS 活动中提交验证；参考坐标不能保证适合所有课堂。最新依据和验证边界见 [GPS 可行性记录](docs/GPS_FEASIBILITY.md) 与 [上游审查记录](docs/UPSTREAM_REVIEW.md)。

## 看门狗与网络

看门狗默认启用；在 `[watchdog]` 设置 `enabled = false` 可关闭。工作进程异常退出或会话失效后，按配置等待并恢复登录；正常退出、Ctrl+C、已识别的认证/依赖/权限/协议错误不反复重启。`once` 和 `demo` 模式直接运行，不启动看门狗。

父子进程通过启动通道在内存中传递凭据和本次配置快照，不写入磁盘、环境变量或命令行参数。配置不会热更新，工作进程重启继续使用本次启动的快照。手动模式恢复后重新确认；自动模式恢复后重新检查本人状态，并可能重新尝试仍待签到的活动。去重状态不跨工作进程保存，结果不确定时应先用正常客户端核验。

看门狗只监督自己创建的工作进程，不监测进程卡死，不能恢复父进程结束、关闭终端、系统关机或重启；不安装开机任务或后台服务。退出时仅清理自己的工作进程。

认证、轮询、取码、数字/GPS 提交及回查统一使用直连会话：`trust_env=False` 并清空会话代理，忽略环境和系统 HTTP 代理，保留 HTTPS 证书验证；不修改系统设置。VPN/TUN 等系统路由仍由操作系统或代理工具控制。认证跳转仅允许浙大认证及课程站的固定 HTTPS 域名。

支持旧 CAS 的动态表单和 RSA 公钥加密，以及标准 Keycloak 用户名密码与 OTP/TOTP 表单。图形验证码、滑块、扫码或定制 JavaScript 验证尚未支持，遇到时明确报错。缺少依赖时，在输入凭据前提示安装命令及当前 Python 路径。

## 开发与检查

所有中文、源文件和配置使用 UTF-8。项目独立实现，没有放入参考仓库的源码或环境目录；Git 提交使用简洁英文。运行依赖见 `requirements.txt`，TOML 读取使用 Python 3.12 标准库，无需新增包。

```powershell
conda activate zju-ac
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
```

测试覆盖认证、直连代理隔离、活动与本人状态区分、提醒去重、退避、手动确认、自动门控入口、去重及失败处理、配置类型和字段验证、UTC 跨日取码、单次 GPS 提交及无距离拒绝、写结果核验，以及真实进程启动后的终端恢复。测试不访问真实签到接口，不需要真实账号。

主要模块：`config.py` 配置加载、`gate.py` 门控入口、`auth.py` 认证、`client.py` 查询与提交、`checkin.py` 手动/自动流程、`gps.py` 坐标验证、`monitor.py` 轮询、`notify.py` 提醒、`watchdog.py` 进程恢复。与最初 XMU-AC 的差异见 [功能对比](docs/FEATURE_COMPARISON.md)。
