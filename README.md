# JX3Tools

[![quality](https://github.com/CrystalSight/astrbot_plugin_jx3tools/actions/workflows/quality.yml/badge.svg)](https://github.com/CrystalSight/astrbot_plugin_jx3tools/actions/workflows/quality.yml)

JX3Tools 是一个 AstrBot 剑网 3 查询插件。它调用注册表中的固定 JX3API 接口，并使用本地
Pillow 与阿里巴巴普惠体 3 生成适合手机阅读的 720 px 单栏图片；查询数据、文章正文和字体
不会发送给远程图片渲染服务。

本项目是非官方社区项目，与 JX3API、JX3BOX、金山软件、西山居及《剑网 3》运营方不存在
隶属或背书关系。

## 兼容性

- AstrBot：`>=4.26.6,<5`
- Python：`>=3.12`
- 运行依赖：`aiohttp>=3.11,<4`、`Pillow>=12,<13`
- Docker 验证基线：AstrBot `4.26.6` / Python `3.12.13`

## 功能

- 免费：日常、月历、行侠、科举、新闻、公告、开服、技改、小药。
- 会员：角色、阵眼、奇遇记录、名剑战绩、金价、诛恶、百战、马场、名片、
  角色百战、今日赤兔、本周赤兔、物品搜索、物价、随机名片、解密。
- 其他：骚话、舔狗。
- 新闻、公告和技改支持 10 秒发起者锁定的序号选择；正文以一张本地图片返回。技改会在
  图片前额外发送所选剑网 3 官网正文链接，新闻和公告不发送链接。
- 名片图片会下载、校验并作为本地图片直接发送，不回复图片 URL。
- 单模式名剑战绩会复用相同区服和角色名获取名片图；名片不可用时自动回退原有战绩布局。
- 月历、小药、奇遇记录、名剑战绩、金价和百战使用各自定制的移动端图片布局。奇遇记录使用
  项目新制的透明水墨名称徽记；百战使用无头像的 10 列蛇形路线。
- 物品搜索会先逐行发送可复制名称；物品搜索和物价仅嵌入通过安全校验的商品图片。

## 安装

在 AstrBot 根目录的 `data/plugins` 下克隆本仓库：

```bash
git clone https://github.com/CrystalSight/astrbot_plugin_jx3tools.git \
  data/plugins/astrbot_plugin_jx3tools
```

AstrBot 会根据 `requirements.txt` 安装运行依赖。重载插件或重启 AstrBot 后，在日志中确认
`astrbot_plugin_jx3tools` 已成功初始化且没有 traceback。

### 安装字体

字体不随本项目分发。请从官方字体包中取得以下两个原始 TTF，并复制到：

```text
AstrBot/data/plugin_data/astrbot_plugin_jx3tools/fonts/
├── AlibabaPuHuiTi-3-55-Regular.ttf
└── AlibabaPuHuiTi-3-75-SemiBold.ttf
```

若 Docker Compose 使用 `./data:/AstrBot/data`，对应宿主机路径为：

```text
<Compose目录>/data/plugin_data/astrbot_plugin_jx3tools/fonts/
```

字体目录位于独立的 `data/plugin_data`，不会随插件源码更新而删除。字体缺失时插件仍可加载，
图片查询会降级为有界文字，并在日志中提示管理员检查字体路径。不要把字体复制到插件源码目录。

## 配置

配置分为通用设置、JX3API 凭据、功能分组、网络与限流、结果展示五组。

- `api_base_url` 仅接受不含路径、查询和用户信息的 HTTPS 地址。
- 本版本默认使用兼容旧 Token 的备份地址 `https://api.jx3api.com`；新版 API 适配将在后续版本进行。
- 免费、会员、其他功能可分别关闭。
- JX3API Token 只发送给明确需要 Token 的接口；Ticket 只发送给明确需要 Ticket 的接口。
- 角色、交易、随机名片和解密等旧版会员接口需要 Token；阵眼和名剑战绩还需要 Ticket。
  免费功能不携带 Token 或 Ticket。
- Token 和 Ticket 需要由管理员通过 JX3API 的账户或服务渠道取得，不要让聊天用户提供凭据。
- 默认区服只补齐 `server` 参数，聊天用户不能覆盖凭据、URL 或 API 路径。
- `auto` 遵循每个功能的展示设计；`text` 尽量使用文字；`image` 尽量使用图片。开服、解密、
  骚话和舔狗始终使用文字。

AstrBot 将配置保存到：

```text
data/config/astrbot_plugin_jx3tools_config.json
```

该配置文件可能包含 Token/Ticket，不应提交到 Git、附在 Issue 中或发送给第三方。

## 使用

```text
/jx3 帮助
/jx3 帮助 角色
/jx3 指令 全部
/jx3 指令 会员
/jx3 日常
/jx3 日常 梦江南 -1
/jx3 月历
/jx3 行侠 觅宝会
/jx3 科举 DXTGQYJGX
/jx3 新闻 10
/jx3 角色 梦江南 角色名
/jx3 名片 梦江南 角色名
```

帮助中 `<参数>` 表示必填，`[参数]` 表示可选。带空格的参数可以使用引号。

## 网络、数据与隐私

- JX3API 请求限定为管理员配置的 HTTPS 基础地址和插件注册表中的固定旧版 `/data/...`
  路径，使用 POST JSON 且禁用重定向。
- 旧接口若返回指向 JX3API 主站的历史图片地址，插件仅在使用官方备份服务时将主机精确改写为
  `api.jx3api.com`，随后继续执行相同的 HTTPS、重定向、类型和大小校验。
- 新闻、公告和技改正文仅从固定的剑网 3 官网接口读取；只有技改会发送所选列表项经校验、
  规范化后的官网 URL。
- 名片和商品图片只从受信 HTTPS 域名下载，禁用重定向，并限制内容类型、字节数和像素数。
- 连接中断、5xx、空响应和截断 JSON 最多进行三次有界尝试。
- 插件不缓存角色、交易或文章结果，不保存聊天输入，不记录凭据或完整私人数据。
- 本地结果图片写入系统临时目录，并交由 AstrBot 跟踪清理。
- 字体保存在 `data/plugin_data/astrbot_plugin_jx3tools/fonts`；配置保存在 AstrBot 的
  `data/config`，都不写入插件源码目录。

## 故障排查

- **插件加载但图片查询退化为文字**：检查两份字体文件的名称和 `plugin_data` 路径。
- **提示缺少 Token 或 Ticket**：在 AstrBot 插件配置中填写对应凭据；不要在聊天中发送。
- **旧 Token 提示鉴权失败**：确认基础地址为 `https://api.jx3api.com`，并检查 Token/Ticket
  是否仍有效；不要把凭据写入 Issue 或日志。
- **JX3API 请求失败**：确认基础地址为上述备份地址且不带路径，并检查上游服务状态和 AstrBot 日志。
- **更新后仍是旧代码**：确认 Git 工作树已更新并通过 AstrBot 插件管理器重载本插件。

## 开发与验证

```bash
python -m pip install -r requirements.txt
python -m pip install "ruff>=0.15.0" "pyright>=1.1.400" \
  "pytest>=8.4.1" "pytest-asyncio>=1.1.0"
ruff check .
pyright
pytest
python scripts/build_adventure_badges.py --check
```

维护奇遇徽记时，从 Google Fonts 官方分发取得 `MaShanZheng-Regular.ttf`，将字体路径显式
传给离线构建脚本：

```text
python scripts/build_adventure_badges.py --font <MaShanZheng-Regular.ttf 路径>
```

脚本只读取版本化名称清单、水墨母版和本地字体，不访问网络，也不会删除旧文件。字体仅用于
生成透明 PNG，不进入插件源码或运行时。构建模式会在写文件前校验字体 SHA-256 并报告缺字；
错误或不同版本的字体不会改写现有徽记。少量生僻字可由清单显式声明的项目自制透明整词蒙版
覆盖，`--check` 无需字体即可复核蒙版与正式徽记。新名称在正式徽记补齐前仍会使用本地可读
回退；异常超长或多行名称会折叠空白、限制为最多两行并受控省略，避免越出徽记。

行为变更还需执行匹配版本的 Docker import、isolated load、正式容器重载和代表性真实冒烟。

## 安全与反馈

普通缺陷和功能建议可使用
[GitHub Issues](https://github.com/CrystalSight/astrbot_plugin_jx3tools/issues)。安全问题请遵循
[SECURITY.md](SECURITY.md)，不要在公开 Issue 中提交凭据、聊天记录或未脱敏日志。

## 许可证与第三方材料

项目自有代码、文档和新制水墨徽记采用 [MIT License](LICENSE)。旧 JX3BOX 来源缩略图不随
本仓库分发且不再由维护脚本下载；Ma Shan Zheng 仅作为 OFL 离线制图工具，字体文件不分发。
阿里巴巴普惠体 3、第三方名称、商标及游戏素材不自动包含在 MIT 授权中；详见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
