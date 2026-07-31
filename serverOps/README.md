# serverOps

一个 [MCP](https://modelcontextprotocol.io) 服务器,用于从**单一入口操作多个远端服务**:
SSH 主机、Docker 守护进程、Kubernetes 集群,以及数据库(PostgreSQL / MySQL / SQLite / Redis / ClickHouse)。
基于 [FastMCP](https://gofastmcp.com) 构建。接入 Claude Code / Claude Desktop 后,
模型即可通过一组小巧、受安全策略约束的工具来执行运维操作。

## 为什么需要它

与其为每个远端服务各跑一个 MCP 服务器,serverOps 是**面向整个集群**的:
你在一份 YAML 文件里声明若干**命名连接(connection profiles)**,所有工具都通过连接名来引用目标。
原始凭据永远不会作为工具参数传递——它们只存在于环境变量中,由配置文件按名引用。

每一次操作都会经过安全层(只读开关、SSH 命令黑名单),写入审计日志,
并在任何错误返回给模型之前先脱敏。

## 功能特性

- **统一接入**:一个服务器同时管理 SSH、Docker、K8s、多种数据库
- **命名连接**:工具只认连接名,不暴露主机/密码
- **物理只读查询**:`db_query` 强制在回滚的事务中执行,误传 `INSERT` 也不会落库
- **只读开关**:全局或单连接级别,一键禁用所有写操作
- **SSH 命令黑名单/白名单**:拦截 `rm -rf /`、`mkfs`、`dd of=/dev/` 等危险命令
- **审计日志**:每次写操作记录一行 JSONL(谁/何时/哪个连接/什么操作)
- **凭据脱敏**:URL 中的密码、错误信息里的密钥在返回模型前被擦除
- **双传输**:本地 stdio(默认)和 HTTP(多客户端/远程,可选 Bearer Token 鉴权)
- **按需安装**:每种后端是可选 extra,未安装只在用到该连接时报错

## 目录

- [安装](#安装)
- [快速部署(一键)](#快速部署一键)
- [配置](#配置)
- [运行](#运行)
- [HTTP 部署(供多端共用)](#http-部署供多端共用)
- [接入客户端](#接入客户端)
- [工具参考(含示例)](#工具参考含示例)
  - [元信息工具](#元信息工具)
  - [SSH 工具](#ssh-工具)
  - [Docker 工具](#docker-工具)
  - [Kubernetes 工具](#kubernetes-工具)
  - [数据库工具](#数据库工具)
- [实战示例](#实战示例)
- [安全模型](#安全模型)
- [开发](#开发)
- [常见问题](#常见问题)

---

## 安装

```bash
python -m venv .venv && .venv/Scripts/activate     # Linux/macOS: source .venv/bin/activate
python -m pip install -e .

# 只安装你真正会用到的后端(可选 extra):
python -m pip install -e ".[ssh]"          # asyncssh
python -m pip install -e ".[container]"    # aiodocker
python -m pip install -e ".[k8s]"          # kubernetes
python -m pip install -e ".[db]"           # sqlalchemy + asyncpg/aiomysql/aiosqlite + redis + clickhouse-connect
python -m pip install -e ".[all]"          # 全部后端
python -m pip install -e ".[dev]"          # pytest、pytest-asyncio、ruff
```

每个连接器的重型库都是**惰性导入**的:未安装的 extra 只在真正用到该连接时报错(并给出安装提示),
不会影响启动。

> **Python 版本提示**:核心(`fastmcp` + `pydantic` + SQLite)在 Python 3.14 上可用。
> 但 `asyncpg`、`aiodocker`、`kubernetes` 等含 C 扩展/原生绑定的库,在 3.14 上可能还没有预编译 wheel。
> 若需要全部后端,推荐使用 **Python 3.12 或 3.13**。

---

## 快速部署(一键)

不想手动建 venv、装依赖、写 `.mcp.json`?用仓库根目录的 [`setup_mcp.py`](../setup_mcp.py)
一条命令搞定(Windows / Linux / macOS 通用,只需任意 Python ≥ 3.10):

```bash
python setup_mcp.py                 # 默认安装全部后端(等同 [all])
python setup_mcp.py --extras db      # 只装你需要的:ssh | container | k8s | db | all | none
python setup_mcp.py --skip-install   # venv 已就绪,只重新生成 .mcp.json
```

它会:

1. 用当前解释器创建 `serverOps/.venv`(已存在则跳过);
2. `pip install -e 'serverOps[<extras>]'` 到该 venv;
3. 从示例种子 `config/servers.yaml` 与 `.env`(**已存在的真实文件一律保留,不会被覆盖**);
4. 生成最小的 `.mcp.json` —— 只含三条路径:`command`(venv 里的 python)、`SERVEROPS_CONFIG`、`SERVEROPS_SECRETS`。

完成后:把所有密码/密钥填进**同一个 `.env`**(见下文),改好 `servers.yaml`,重载客户端即可。

> 这样 `.mcp.json` 不再需要逐条列出 `WEB1_SSH_PASSWORD` 之类的密钥 ——
> 密钥全部集中在 `.env`,与启动器和拓扑配置彻底解耦。

---

## 配置

创建 `~/.serverops/config.yaml`(或用 `SERVEROPS_CONFIG` 指定路径)。
完整模板见 [`config/servers.example.yaml`](config/servers.example.yaml)。

### 全局设置(`settings`)

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `read_only` | bool | `false` | 全局只读开关。为 `true` 时**所有写操作**被禁用 |
| `ssh_command_denylist` | 正则列表 | 内置危险命令 | 匹配任一正则的 SSH 命令被拒绝(大小写不敏感) |
| `ssh_command_allowlist` | 正则列表 | `[]` | 非空时,只允许匹配的命令(比黑名单更严格) |
| `audit_log` | 路径 | 关闭 | 启用 JSONL 审计日志的路径 |

### SSH 连接(`kind: ssh`)

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `host` | ✅ | — | 主机名或 IP |
| `user` | ✅ | — | 登录用户 |
| `port` | | `22` | 端口 |
| `key_path` | | — | 私钥路径(如 `~/.ssh/id_ed25519`) |
| `password_env` | | — | 密码所在的环境变量名(替代密钥认证) |
| `known_hosts` | | `strict` | `strict`(校验 known_hosts)/`accept-new`/`ignore`(不安全) |
| `read_only` | | `false` | 该连接只读 |
| `description` | | — | 备注 |

### Docker 连接(`kind: docker`)

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `url` | | `unix:///var/run/docker.sock` | Docker daemon 地址(unix socket 或 tcp+TLS) |
| `tls_verify` | | `false` | 启用 TLS 校验 |
| `cert_path` | | — | TLS 证书目录 |

### Kubernetes 连接(`kind: kubernetes`)

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `kubeconfig` | | — | kubeconfig 文件路径(留空则在 Pod 内用集群内配置) |
| `context` | | — | 使用的 context |
| `in_cluster` | | `false` | 在集群内运行时设为 `true` |
| `namespace` | | `default` | 默认命名空间(工具可覆盖) |

### 数据库连接(`kind: postgres / mysql / sqlite / redis / clickhouse`)

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `url` | ✅ | — | 连接 URL。用 `${ENV_VAR}` 从环境注入密钥 |
| `read_only` | | `false` | 该连接只读(连 `db_execute` 也禁用)。ClickHouse 天生只查询,见下文 |

> URL 写法示例:
> - postgres: `postgresql://user:pass@host:5432/db`(自动转为 `postgresql+asyncpg://`)
> - mysql: `mysql://user:pass@host:3306/db`(自动转为 `mysql+aiomysql://`)
> - sqlite: `sqlite:///./app.db`(自动转为 `sqlite+aiosqlite:///`)
> - redis: `redis://:pass@host:6379/0`
> - clickhouse: `clickhouse://user:pass@host:8123/db`(HTTP,默认 8123);HTTPS 用
>   `clickhouse+https://user:pass@host:8443/db`(或 `clickhouses://`,默认 8443)。

### 完整配置示例

```yaml
settings:
  read_only: false                 # 全局只读开关:为 true 则禁用所有写操作
  ssh_command_denylist:            # 匹配这些正则的 SSH 命令会被拒绝
    - '\brm\s+-rf\s+/(?:\s|$)'
  # ssh_command_allowlist:          # 非空时只允许列出的命令(更严格)
  #   - '\bdf\b'
  #   - '\buptime\b'
  audit_log: ~/.serverops/audit.jsonl

connections:
  # SSH 主机
  web1:
    kind: ssh
    description: "前端 Web 主机"
    host: web1.example.com
    user: deploy
    key_path: ~/.ssh/id_ed25519
    known_hosts: strict

  # Docker daemon(本地 socket)
  docker-local:
    kind: docker
    url: unix:///var/run/docker.sock

  # Kubernetes 集群
  prod-cluster:
    kind: kubernetes
    description: "生产集群"
    kubeconfig: ~/.kube/config
    context: prod
    namespace: default

  # 数据库 —— URL 从环境变量注入,密钥永不写进配置文件
  analytics-db:
    kind: postgres
    description: "分析库(只读副本)"
    url: "${ANALYTICS_DB_URL}"
    read_only: true

  cache:
    kind: redis
    url: "${REDIS_URL}"

  scratch:
    kind: sqlite
    url: "sqlite:///./local.db"
```

对应的 `.env`(所有密钥集中在这一个文件,详见下文「[密钥集中管理](#密钥集中管理env-文件)」):

```bash
# serverOps/.env
ANALYTICS_DB_URL=postgresql://reader:hunter2@db.host:5432/analytics
REDIS_URL=redis://:secret@cache.host:6379/0
WEB1_SSH_PASSWORD=...        # 配合 servers.yaml 里的 password_env 使用
```

> **密钥集中在 `.env`,绝不写进 `servers.yaml`**:DB URL 用 `${VAR}` 插值,SSH 密码用 `password_env`。
> 启动时 `.env` 被加载进环境变量(已有的环境变量不会被覆盖),`servers.yaml` 本身不含任何密钥。

### 密钥集中管理(`.env` 文件)

所有密码 / 密钥 / 连接 URL 都写在**同一个 dotenv 文件**(默认 `serverOps/.env`)。
启动时 serverOps 在读取 `servers.yaml` **之前**把它加载进环境变量,既有的 `${VAR}`
插值和 `password_env` 机制原样生效 —— 因此 **`servers.yaml` 一个字都不用改**,`.env` 只是一个
纯叠加的密钥侧通道。

**查找顺序**(命中即停):`--secrets` / `SERVEROPS_SECRETS` 指定的路径 → `servers.yaml`
同目录或上一级目录的 `.env` → `~/.serverops/.env` → 不加载(很多连接用密钥认证/sqlite,无需密钥)。

**覆盖策略**:已在环境里的变量**永不被覆盖** —— shell / CI / `.mcp.json` 的 `env` 始终优先,
运维可以不改文件就临时覆盖某个值。

`.env` 写法就是 `KEY=VALUE`(可选 `export` 前缀、可选引号);`#` 只在行首作注释,
值里的 `#` 会被原样保留(密码常含 `#`,所以**不支持行内注释**,带特殊字符的值用引号包起来):

```bash
# serverOps/.env
WEB1_SSH_PASSWORD=p@ssw0rd
ANALYTICS_DB_URL="postgresql://reader:hunter2@db.host:5432/analytics"   # 引号可选
REDIS_URL=redis://:secret@cache.host:6379/0
```

> 显式指定密钥文件:`SERVEROPS_SECRETS=/abs/path/to/.env`(放进 `.mcp.json` 的 `env` 或 shell)。
> `.env` 已在 `.gitignore` 中,**切勿提交真实密钥**。

---

## 运行

```bash
# stdio(默认)——供 Claude Code / Claude Desktop 调用
python -m serverops

# HTTP(streamable)——多客户端 / 远程访问
python -m serverops --transport http --host 127.0.0.1 --port 8000
# MCP 端点: http://127.0.0.1:8000/mcp
# 健康检查: http://127.0.0.1:8000/health
```

所有命令行参数都可用环境变量覆盖:

| 环境变量 | 作用 |
|---|---|
| `SERVEROPS_CONFIG` | 配置文件路径 |
| `SERVEROPS_SECRETS` | `.env` 密钥文件路径(留空则按上文顺序自动查找) |
| `SERVEROPS_TRANSPORT` | `stdio` 或 `http` |
| `SERVEROPS_HOST` | HTTP 绑定地址(默认 `127.0.0.1`) |
| `SERVEROPS_PORT` | HTTP 端口(默认 `8000`) |
| `SERVEROPS_HTTP_TOKEN` | HTTP 模式的共享 Bearer Token(见下) |

### 给 HTTP 加鉴权

暴露到网络上时,务必设置共享 Token:

```bash
export SERVEROPS_HTTP_TOKEN="$(openssl rand -hex 32)"
python -m serverops --transport http
```

客户端请求时带上 `Authorization: Bearer <token>`。不带或带错 → `401 Unauthorized`。

---

## HTTP 部署(供多端共用)

stdio 模式下,每个客户端都要各自起一份 serverOps 进程;HTTP(streamable)模式则把
serverOps 跑成**一个常驻服务**,所有客户端共用同一个端点 + 同一个 Bearer Token ——
适合团队共用、远程访问,以及多客户端(Claude Code / Desktop / Cursor / Continue / 自研脚本)接入。

### 启动

```bash
# 1) 生成一个高强度共享 Token
export SERVEROPS_HTTP_TOKEN="$(openssl rand -hex 32)"
export SERVEROPS_CONFIG=/opt/serverOps/config/servers.yaml
export SERVEROPS_SECRETS=/opt/serverOps/.env

# 2) 启动(生产环境只绑 127.0.0.1,对外暴露交给反向代理)
python -m serverops --transport http --host 127.0.0.1 --port 8000
# MCP 端点: http://127.0.0.1:8000/mcp
# 健康检查: http://127.0.0.1:8000/health  (免鉴权,只返回 {"status":"ok"})
```

所有参数均可由环境变量覆盖(见[运行](#运行))。`SERVEROPS_HTTP_TOKEN` 留空时,
HTTP 传输**完全无鉴权** —— 仅适合受信任的本地网络。

> Token 校验用 `hmac.compare_digest` 恒定时间比较(`http_auth.py`)。
> 需要按实例 / 按用途区分 Token 时,用 `SERVEROPS_HTTP_TOKEN_ENV` 指定实际读取的变量名。

### 守护进程(长驻)

**Linux(systemd):**

```ini
# /etc/systemd/system/serverops-mcp.service
[Unit]
Description=serverOps MCP (HTTP)
After=network.target

[Service]
Type=simple
User=serverops
WorkingDirectory=/opt/serverOps
Environment=SERVEROPS_CONFIG=/opt/serverOps/config/servers.yaml
Environment=SERVEROPS_SECRETS=/opt/serverOps/.env
Environment=SERVEROPS_HTTP_TOKEN=__填上面生成的 Token__
ExecStart=/opt/serverOps/.venv/bin/python -m serverops --transport http --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now serverops-mcp
```

**Windows(NSSM 注册为服务):**

```powershell
nssm install serverops "C:\serverOps\.venv\Scripts\python.exe" "-m serverops --transport http --host 127.0.0.1 --port 8000"
nssm set serverops AppDirectory C:\serverOps
nssm set serverops AppEnvironmentExtra SERVEROPS_CONFIG=C:\serverOps\config\servers.yaml SERVEROPS_SECRETS=C:\serverOps\.env SERVEROPS_HTTP_TOKEN=__Token__
nssm start serverops
```

### 反向代理 + TLS

Bearer Token 走明文 HTTP 会被嗅探,暴露到公网**必须**套 HTTPS。MCP 的 streamable HTTP
含 SSE 长连接(GET),nginx 要关闭缓冲、拉长读写超时,否则长连接会被提前掐断:

```nginx
# /etc/nginx/sites-available/mcp.conf
server {
    listen 443 ssl http2;
    server_name mcp.example.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    # 可选:只放行已知客户端 IP
    # allow 203.0.113.10; deny all;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # ⚠️ MCP streamable HTTP = POST(JSON-RPC)+ GET(SSE)长连接
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}

server {  # 80 强制跳 TLS
    listen 80;
    server_name mcp.example.com;
    return 301 https://$host$request_uri;
}
```

```bash
sudo certbot --nginx -d mcp.example.com   # 自动签发 Let's Encrypt 证书
```

### 各客户端接入

所有客户端填**同一个 URL + 同一个 Token**即可,无需各自启动 server 进程。

**Claude Code(命令行):**

```bash
claude mcp add --transport http serverops https://mcp.example.com/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

**Claude Desktop**(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "serverops": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer <TOKEN>" }
    }
  }
}
```

**Cursor**(`.cursor/mcp.json`)/ **Continue** / 其他兼容 MCP 的客户端:

```json
{
  "mcpServers": {
    "serverops": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer <TOKEN>" }
    }
  }
}
```

> 不同客户端版本字段名略有差异(`url` / `serverUrl` / 是否需要 `transport: "http"`),
> 按报错微调即可。

**curl 手动验证:**

```bash
# 1) initialize 握手
curl -X POST https://mcp.example.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $SERVEROPS_HTTP_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-06-18","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1"}}}'
# 不带 / 带错 Token → 401 Unauthorized
```

**Python 客户端**(基于 FastMCP 的 Client):

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("https://mcp.example.com/mcp",
                      auth="<TOKEN>") as client:
        tools = await client.list_tools()
        print([t.name for t in tools])

        result = await client.call_tool("connection_list", {})
        print(result.data)

asyncio.run(main())
```

### 安全清单

| 项 | 要求 | 说明 |
|---|---|---|
| Bearer Token | **必设** | 留空则 HTTP 完全无鉴权(仅 Token 非空时才挂 `StaticTokenVerifier`) |
| TLS | **必开** | Token 明文走 HTTP 会被嗅探 |
| 绑定地址 | 生产绑 `127.0.0.1` | 对外暴露交给反向代理 |
| `/health` | 可对外暴露 | 独立路由,不走鉴权,只返回 `{"status":"ok"}`,适合探活 |
| 审计日志 | 开启 | `settings.audit_log` 记录每次写操作(见[安全模型](#安全模型)) |
| 只读开关 | 高危连接设 `read_only: true` | 受只读约束的写操作会被拦截 |
| Token 轮换 | 多实例用 `SERVEROPS_HTTP_TOKEN_ENV` 区分 | 按用途 / 按客户端隔离 |

---

## 接入客户端

### Claude Code(项目级 `.mcp.json`)

复制 [`.mcp.json.example`](.mcp.json.example) 为 `.mcp.json`,改成你的路径:

```json
{
  "mcpServers": {
    "serverops": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/serverOps", "-m", "serverops"],
      "env": {
        "SERVEROPS_CONFIG": "/path/to/servers.yaml",
        "SERVEROPS_SECRETS": "/path/to/.env"
      }
    }
  }
}
```

如果不用 `uv`,也可以直接:

```json
{
  "mcpServers": {
    "serverops": {
      "command": "/path/to/serverOps/.venv/bin/python",
      "args": ["-m", "serverops"],
      "env": {
        "SERVEROPS_CONFIG": "/path/to/servers.yaml",
        "SERVEROPS_SECRETS": "/path/to/.env"
      }
    }
  }
}
```

> 想省去手写?直接跑 `python setup_mcp.py`(见[快速部署](#快速部署一键)),它会自动生成上面的 `.mcp.json`。
> `.mcp.json` 里**不再需要**列出 `WEB1_SSH_PASSWORD` 等密钥 —— 它们都在 `.env` 里。

### HTTP 模式接入

远程 / 多端 HTTP 接入(常驻服务、反向代理 + TLS、各客户端配置、curl 与 Python 客户端示例)
见上文 [HTTP 部署(供多端共用)](#http-部署供多端共用)。

---

## 工具参考(含示例)

所有工具都是异步的,**第一个参数永远是 `connection`(连接名)**,返回 JSON。
写操作受只读开关和安全层约束。下面的"调用示例"展示的是结构化参数;
在 Claude 里你只需用自然语言描述需求,模型会自行选择工具并填参。

### 元信息工具

#### `connection_list` — 列出所有连接

```jsonc
// 调用
connection_list()

// 返回
{
  "connections": [
    {"name": "web1",          "kind": "ssh",        "read_only": false, "description": "前端 Web 主机"},
    {"name": "analytics-db",  "kind": "postgres",   "read_only": true,  "description": "分析库(只读副本)"},
    {"name": "docker-local",  "kind": "docker",     "read_only": false, "description": null},
    {"name": "prod-cluster",  "kind": "kubernetes", "read_only": false, "description": "生产集群"}
  ],
  "count": 4
}
```

#### `connection_ping` — 探测某个连接是否可达

```jsonc
// 调用
connection_ping(connection="web1")

// 返回(成功)
{"connection": "web1", "healthy": true, "detail": ""}

// 返回(失败)
{"connection": "web1", "healthy": false, "detail": "SSH connect to deploy@web1:22 failed: ..."}
```

#### `connection_info` — 查看连接详情(凭据已脱敏)

```jsonc
// 调用
connection_info(connection="analytics-db")

// 返回 —— 注意 url 里的密码被替换成 ***
{
  "kind": "postgres",
  "description": "分析库(只读副本)",
  "read_only": true,
  "url": "postgresql://reader:***@db.host:5432/analytics"
}
```

#### `server_health` — 全部连接的汇总健康状态

```jsonc
// 调用
server_health()

// 返回
{
  "healthy": 3,
  "total": 4,
  "connections": [
    {"name": "web1",          "healthy": true},
    {"name": "analytics-db",  "healthy": true},
    {"name": "docker-local",  "healthy": true},
    {"name": "prod-cluster",  "healthy": false, "detail": "..."}
  ]
}
```

---

### SSH 工具

#### `ssh_exec` — 在远端执行一条命令

```jsonc
// 调用:查看磁盘占用
ssh_exec(connection="web1", command="df -h", timeout=30)

// 返回
{
  "exit_status": 0,
  "stdout": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/vda1       40G   18G   20G  48% /\n...",
  "stderr": ""
}
```

```jsonc
// 调用:查看服务状态
ssh_exec(connection="web1", command="systemctl is-active nginx")
// → {"exit_status": 0, "stdout": "active\n", "stderr": ""}
```

> ⚠️ 只读模式下 `ssh_exec` 被禁用;危险命令(`rm -rf /` 等)即使非只读也会被黑名单拦截。

#### `ssh_script` — 执行多行脚本

```jsonc
// 调用:批量检查多台……(这里在同一台跑多行)
ssh_script(connection="web1", script="for svc in nginx php-fpm; do echo \"$svc: $(systemctl is-active $svc)\"; done")

// 返回
{
  "exit_status": 0,
  "stdout": "nginx: active\nphp-fpm: active\n",
  "stderr": ""
}
```

脚本通过 `sh -s` 从 stdin 传入,无需担心引号转义。

#### `ssh_upload` / `ssh_download` — SFTP 文件传输

```jsonc
// 上传部署包
ssh_upload(connection="web1", local_path="/builds/app.tar.gz", remote_path="/srv/app.tar.gz")
// → {"remote_path": "/srv/app.tar.gz", "bytes": 18432000}

// 拉回日志分析
ssh_download(connection="web1", remote_path="/var/log/nginx/access.log", local_path="./access.log")
// → {"remote_path": "/var/log/nginx/access.log", "local_path": "/abs/path/access.log"}
```

---

### Docker 工具

#### `docker_ps` — 列出容器

```jsonc
// 调用
docker_ps(connection="docker-local", all=true)

// 返回
{
  "containers": [
    {"id": "a1b2c3d4", "name": "web",     "image": "nginx:1.27", "state": "running", "status": "Up 3 days"},
    {"id": "e5f6a7b8", "name": "redis",   "image": "redis:7",    "state": "running", "status": "Up 3 days"},
    {"id": "9c0d1e2f", "name": "worker",  "image": "app:latest", "state": "exited",  "status": "Exited (0) 2 hours ago"}
  ]
}
```

> `all=false` 时只返回运行中的容器。

#### `docker_logs` — 查看容器日志

```jsonc
// 调用:取最近 100 行
docker_logs(connection="docker-local", container="web", tail=100)

// 返回
{"logs": "10.0.0.1 - - [27/Jul/2026:12:00:01] \"GET / HTTP/1.1\" 200 ...\n..."}
```

#### `docker_exec` — 在容器内执行命令(受只读约束)

```jsonc
// 调用:看容器里的环境变量
docker_exec(connection="docker-local", container="web", command="env | grep APP")

// 返回
{"exit_code": 0, "output": "APP_ENV=production\nAPP_VERSION=2.4.1\n"}
```

```jsonc
// 只读模式下被拦截
docker_exec(connection="docker-local", container="web", command="rm -rf /tmp/cache")
// → 抛出 SafetyError:"Operation 'docker_exec' is blocked because read-only mode is enabled."
```

#### `docker_stats` — 资源占用快照

```jsonc
// 调用
docker_stats(connection="docker-local", container="web")

// 返回
{
  "name": "web",
  "state": "running",
  "memory_usage_mb": 48.5,
  "memory_limit_mb": 512.0,
  "cpu_count": 2
}
```

---

### Kubernetes 工具

#### `k8s_list_pods` — 列出 Pod

```jsonc
// 调用(用连接默认命名空间)
k8s_list_pods(connection="prod-cluster")

// 指定命名空间
k8s_list_pods(connection="prod-cluster", namespace="kube-system")

// 返回
{
  "pods": [
    {"name": "api-7b9f-x9yz", "namespace": "default", "phase": "Running",
     "pod_ip": "10.244.1.5", "node": "node-pool-1"},
    {"name": "api-7b9f-ab12", "namespace": "default", "phase": "Running",
     "pod_ip": "10.244.2.7", "node": "node-pool-2"}
  ]
}
```

#### `k8s_pod_logs` — 查看 Pod 日志

```jsonc
// 调用
k8s_pod_logs(connection="prod-cluster", name="api-7b9f-x9yz", tail=200)

// 返回
{"logs": "INFO  starting api server on :8080\nINFO  request handled method=GET path=/health\n..."}
```

#### `k8s_describe` — 查看 Pod 关键字段

```jsonc
// 调用
k8s_describe(connection="prod-cluster", name="api-7b9f-x9yz")

// 返回(精简后的字段,不含 secret/configmap 原始数据)
{
  "pod": {
    "name": "api-7b9f-x9yz",
    "namespace": "default",
    "phase": "Running",
    "pod_ip": "10.244.1.5",
    "node": "node-pool-1",
    "host_ip": "10.0.1.10",
    "started_at": "2026-07-27T08:00:00Z"
  }
}
```

#### `k8s_exec` — 在 Pod 内执行命令(受只读约束)

```jsonc
// 调用:看容器工作目录
k8s_exec(connection="prod-cluster", name="api-7b9f-x9yz", command="ls /app")

// 返回
{"output": "main.py\nrequirements.txt\nconfig/\n"}
```

---

### 数据库工具

> **命名参数**:SQL 用 `:name` 占位符,值放在 `params` 字典里(跨数据库安全)。
> 例如 `sql="SELECT * FROM users WHERE id = :id"`,`params={"id": 1}`。

#### `db_query` — 只读查询(物理只读)

```jsonc
// 调用:统计行数
db_query(connection="analytics-db", sql="SELECT count(*) AS n FROM events")

// 返回
{"columns": ["n"], "rows": [[4821390]], "row_count": 1}
```

```jsonc
// 调用:带参数
db_query(
  connection="analytics-db",
  sql="SELECT id, email FROM users WHERE created_at > :since ORDER BY id LIMIT 5",
  params={"since": "2026-01-01"}
)
// → {"columns": ["id","email"], "rows": [[101,"a@x.com"],[102,"b@x.com"]], "row_count": 2}
```

> 🛡️ **物理只读保证**:`db_query` 总在回滚的事务里执行。
> 即使误传 `INSERT/UPDATE/DELETE`,也会被回滚,不会落库。实测:通过 `db_query`
> 执行 `INSERT` 后再 `SELECT count(*)`,行数不变。

#### `db_execute` — 写操作(受只读约束)

```jsonc
// 调用:建表
db_execute(connection="scratch",
           sql="CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
// → {"rowcount": -1}

// 调用:带参数插入
db_execute(connection="scratch",
           sql="INSERT INTO notes (id, body) VALUES (:id, :body)",
           params={"id": 1, "body": "hello"})
// → {"rowcount": 1}
```

```jsonc
// 只读连接上被拦截
db_execute(connection="analytics-db", sql="DELETE FROM events WHERE id < 100")
// → 抛出 SafetyError(analytics-db 配置了 read_only: true)
```

#### `db_tables` / `db_schema` — 表结构探查

```jsonc
// 调用:列出所有表
db_tables(connection="analytics-db")
// → {"tables": ["events", "users", "sessions"]}

// 调用:查看某张表的列
db_schema(connection="analytics-db", table="users")
// → {
//     "table": "users",
//     "columns": [
//       {"name": "id",         "type": "INTEGER",      "nullable": false, "default": null},
//       {"name": "email",      "type": "VARCHAR(255)", "nullable": false, "default": null},
//       {"name": "created_at", "type": "TIMESTAMP",    "nullable": true,  "default": "now()"}
//     ]
//   }
```

#### Redis(经 `db_query`)

Redis 没有表概念,把单条命令写在 `sql` 里,以空格拆分:

```jsonc
db_query(connection="cache", sql="GET session:42")
// → {"value": "{\"user_id\":7,...}"}

db_query(connection="cache", sql="HGETALL config:flags")
// → {"value": {"feature_x": "on", "feature_y": "off"}}

db_query(connection="cache", sql="TTL session:42")
// → {"value": 318}
```

> `db_execute` / `db_tables` / `db_schema` **不支持 Redis**(会返回明确错误)。
> 需要写 Redis,直接用 `db_query` 传写命令即可(注意:Redis 写操作不归只读开关管,
> 请用配置层面的访问控制来约束)。

#### ClickHouse(只查询,经 `db_query`)

ClickHouse 按**只查询**接入:只能读数据,**任何写操作一律禁止**(与 `read_only` 开关无关)。

```jsonc
// 查询
db_query(connection="olap", sql="SELECT count() FROM events WHERE day = :day", params={"day": "2026-07-28"})
// → {"columns": ["count()"], "rows": [[4821390]], "row_count": 1}

// 探查表结构(只读)
db_tables(connection="olap")          // → {"tables": ["events", "users"]}
db_schema(connection="olap", table="users")  // 列名/类型/可空/默认值
```

> 🛡️ **ClickHouse 的只读保证**不同于 SQL 后端:ClickHouse 没有事务/回滚,
> 所以 `db_query` 用**语句首关键字白名单**(只放行 `SELECT / WITH / SHOW / DESCRIBE /
> EXPLAIN / EXISTS`)来保证不会落写;`INSERT / CREATE / DROP / ALTER / TRUNCATE / …`
> 会被直接拒绝。`db_execute` 对 ClickHouse **始终禁用**(无论 `read_only` 是否开启)。
>
> 参数绑定沿用 `:name` 约定,内部转成 ClickHouse 的 `%(name)s` 风格;`::Type` 类型转换不受影响。
> 注意:带参数的 SQL 里若出现字面量 `%`,需写成 `%%`(Python 格式化转义)。

---

## 实战示例

下面展示几个真实场景下,模型如何串起多个工具。

### 场景 1:排查"网站慢了"

```
你:web1 上的网站响应变慢,帮我看看。

模型(自动):
1. connection_ping("web1")                  → 确认主机可达
2. ssh_exec("web1", "uptime")               → 看负载 (load average)
3. ssh_exec("web1", "free -m")              → 看内存
4. ssh_exec("web1", "df -h /")              → 看磁盘
5. ssh_exec("web1", "systemctl status nginx")
6. docker_stats("docker-local", "web")      → 看 Web 容器资源占用
→ 汇总诊断:"负载正常,内存 92% 接近上限,nginx worker 已达上限……"
```

### 场景 2:核查生产数据(只读)

```
你:过去一小时 analytics-db 里有多少笔下单失败?

模型:
1. db_query("analytics-db",
     "SELECT count(*) FROM orders WHERE status='failed' AND created_at > :since",
     {"since": "2026-07-27T11:00:00Z"})
→ 即便手滑写成带 UPDATE 的语句,也因回滚而无副作用。
```

### 场景 3:从 Pod 抓日志定位报错

```
你:prod-cluster 里 api 服务有 5xx,帮我查。

模型:
1. k8s_list_pods("prod-cluster")                        → 拿到 Pod 名
2. k8s_pod_logs("prod-cluster", name="api-7b9f-x9yz", tail=500)
3. k8s_exec("prod-cluster", name="api-7b9f-x9yz", command="env | grep LOG_LEVEL")
→ 定位到是某个环境变量配错导致。
```

### 审计日志样例(`audit.jsonl`)

开启 `audit_log` 后,每次写操作记一行:

```json
{"ts":"2026-07-27T12:00:01.123456+00:00","pid":42180,"connection":"web1","operation":"ssh_exec","status":"ok","detail":"df -h"}
{"ts":"2026-07-27T12:00:03.770011+00:00","pid":42180,"connection":"scratch","operation":"db_execute","status":"ok","detail":"INSERT INTO notes (id, body) VALUES (:id, :body)"}
{"ts":"2026-07-27T12:00:05.112044+00:00","pid":42180,"connection":"docker-local","operation":"docker_exec","status":"ok","detail":"web: env | grep APP"}
```

> `detail` 会被截断到 200 字符;命令原文保留用于审计追查。

---

## 安全模型

- **仅命名连接访问** —— 工具从不接受原始主机/凭据参数,模型无法越权访问配置之外的资源。
- **只读模式** —— 全局 `settings.read_only` 或单连接 `read_only`;为真时禁用
  `ssh_exec`、`ssh_script`、`docker_exec`、`k8s_exec`、`db_execute`。
- **SSH 命令黑名单** —— 拦截 `rm -rf /`、`mkfs`、`dd of=/dev/`、`shutdown`、
  fork bomb 等;可选白名单(`ssh_command_allowlist`)可锁定为"只允许列出的命令"。
- **`db_query` 物理只读** —— 每条语句都在回滚的事务中执行,误传写语句也无影响。
- **ClickHouse 只查询** —— `kind: clickhouse` 的连接只允许读:`db_execute` 始终禁用,
  `db_query` 用语句首关键字白名单(只放行 SELECT/SHOW/DESCRIBE 等)拦截一切写语句。
- **审计日志** —— 每次写操作记录一条 JSONL(谁/何时/哪个连接/什么操作)。
- **凭据脱敏** —— URL 里的密码、错误信息中的密钥,在返回模型前被擦除成 `***`。
- **可选 HTTP 鉴权** —— 暴露到网络时用 Bearer Token 守门。

> ⚠️ SSH / 容器 / Pod / 数据库的 exec 本质上是高权限操作。serverOps 让它们**更安全、更可观测**,
> 但一个受信任的连接配置本身就是一项特权——请审慎授予。

---

## 开发

```bash
.venv/Scripts/python -m pytest -q                           # 全部测试 (77+)
.venv/Scripts/python -m ruff check .                        # lint
.venv/Scripts/python -m fastmcp dev src/serverops/server.py # MCP Inspector 可视化调试
```

### 项目结构

```
src/serverops/
  config.py / models.py     配置加载 + 校验后的连接 profile
  secrets.py                .env 密钥文件加载(配置插值前注入环境变量)
  registry.py               连接名 -> 缓存的异步连接器
  safety.py / audit.py      只读 + 命令黑名单 / JSONL 审计日志
  redaction.py              从日志和错误中脱敏
  server.py / __main__.py   FastMCP 应用 + CLI(stdio / http)
  http_auth.py              HTTP 模式的 Bearer Token 鉴权
  connectors/               base + ssh / docker / kubernetes / database
  tools/                    meta / ssh / db / container 工具组
tests/                      每个模块的单元/集成测试(含真实 SQLite + 注入式 mock)
```

---

## 常见问题

**报错 `Unknown connection 'xxx'`**
工具里的连接名拼错了,或该连接没写进配置。先 `connection_list` 看可用连接。

**报错 `... requires the 'ssh'/'container'/'k8s'/'db' extra`**
对应后端库没装。按提示 `pip install 'serverops[ssh]'`(或相应 extra)。

**报错 `Operation 'xxx' is blocked because read-only mode is enabled`**
当前处于只读模式。检查 `settings.read_only` 或该连接的 `read_only`。
只读是有意为之的保护,确认安全后再关闭。

**`asyncssh` / `aiodocker` / `kubernetes` 在 Python 3.14 上装不上**
这些库可能还没有 3.14 的预编译 wheel。改用 Python 3.12/3.13 即可。
核心(server + 元信息工具 + SQLite)在 3.14 上正常工作。

**Docker/K8s 工具的真实行为**
连接器代码遵循真实库的 API,但单元测试用的是注入的 mock。
真实环境(Docker daemon / K8s 集群)下建议先 `docker_ps` / `k8s_list_pods` 做冒烟验证。

## 状态 / 暂未实现

流式大文件传输、云厂商 SSH 认证(SSM/IAP)、托管部署的深度加固(超出 Bearer Token 之外)、
以及 `resources` 接口,暂未实现。每个连接器的库只在用到该 kind 时才需要。
