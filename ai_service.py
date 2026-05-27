"""
DeepSeek AI 服务 + 本地故障知识库

工作逻辑：
1. 用户输入日志或故障描述
2. 先从本地知识库匹配常见故障
3. 如果命中，直接返回预置解决方案，速度快，不消耗 API
4. 如果未命中，再调用 DeepSeek API 进行智能分析
"""

import json
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()


# =========================
# 工具函数：提取关键信息
# =========================

def extract_ports(text):
    """
    从日志中提取端口号。
    支持格式：
    0.0.0.0:80
    127.0.0.1:8080
    port 3306
    port is already allocated 8080
    """
    ports = []

    patterns = [
        r":(\d{2,5})",
        r"port\s+(\d{2,5})",
        r"端口\s*(\d{2,5})",
    ]

    for pattern in patterns:
        found = re.findall(pattern, text, re.IGNORECASE)
        ports.extend(found)

    # 去重并保持顺序
    result = []
    for port in ports:
        if port not in result:
            result.append(port)

    return result


def extract_service_name(text):
    """
    尝试从日志中识别常见服务名。
    """
    lower_text = text.lower()

    services = [
        "nginx",
        "docker",
        "mysql",
        "redis",
        "tomcat",
        "apache",
        "httpd",
        "ssh",
        "sshd",
        "java",
        "node",
        "python",
    ]

    for service in services:
        if service in lower_text:
            return service

    return "对应服务"


def fill_placeholders(commands, log_text):
    """
    将本地知识库命令中的占位符替换为真实信息。
    例如：
    ss -tlnp | grep <PORT> 变成 ss -tlnp | grep :80
    systemctl status <service> 变成 systemctl status nginx
    """
    ports = extract_ports(log_text)
    service_name = extract_service_name(log_text)

    new_commands = []

    for item in commands:
        cmd = item.get("cmd", "")
        desc = item.get("desc", "")
        risk = item.get("risk", "safe")

        if "<PORT>" in cmd:
            if ports:
                cmd = cmd.replace("<PORT>", ":" + ports[0])
            else:
                cmd = cmd.replace("<PORT>", ":实际端口号")
                desc = desc + "，请将实际端口号替换为需要排查的端口"

        if "<service>" in cmd:
            cmd = cmd.replace("<service>", service_name)

        if "<PID>" in cmd:
            cmd = cmd.replace("<PID>", "实际进程PID")
            desc = desc + "，PID 需要先通过 ss 或 lsof 命令查询"

        if "<container>" in cmd:
            cmd = cmd.replace("<container>", "容器名或容器ID")
            desc = desc + "，容器名或容器ID 可通过 docker ps -a 查看"

        if "<backend-port>" in cmd:
            if ports:
                cmd = cmd.replace("<backend-port>", ports[0])
            else:
                cmd = cmd.replace("<backend-port>", "后端服务端口")

        if "<path>" in cmd:
            cmd = cmd.replace("<path>", "实际文件或目录路径")

        if "<web-root>" in cmd:
            cmd = cmd.replace("<web-root>", "网站根目录")

        new_commands.append({
            "cmd": cmd,
            "desc": desc,
            "risk": risk,
        })

    return new_commands


def normalize_result(result):
    """
    统一返回格式，避免前端因为字段缺失报错。
    """
    if not isinstance(result, dict):
        return {
            "fault_type": "返回格式异常",
            "cause": "分析结果不是标准 JSON 字典格式。",
            "commands": [],
            "solution": "请检查 ai_service.py 中的返回格式。",
            "risk_level": "warning",
        }

    return {
        "fault_type": result.get("fault_type", "无法识别"),
        "cause": result.get("cause", "暂无原因分析"),
        "commands": result.get("commands", []),
        "solution": result.get("solution", "暂无解决方案"),
        "risk_level": result.get("risk_level", "info"),
    }


# =========================
# 本地故障知识库
# =========================
# 格式：
# 关键词列表, 故障类型, 原因, 排查命令列表, 解决方案, 风险等级

LOCAL_KB = [
    (
        [
            "connection refused",
            "拒绝连接",
            "connect refused",
            "cannot connect",
            "无法连接",
        ],
        "服务未启动 / 端口未监听",
        "目标端口上没有进程监听，或者防火墙、安全组、服务配置阻止了连接。",
        [
            {"cmd": "ss -tlnp | grep <PORT>", "desc": "检查目标端口是否正在监听", "risk": "safe"},
            {"cmd": "systemctl status <service>", "desc": "检查相关服务运行状态", "risk": "safe"},
            {"cmd": "journalctl -u <service> -n 50 --no-pager", "desc": "查看服务最近日志", "risk": "safe"},
            {"cmd": "firewall-cmd --list-ports", "desc": "查看防火墙已开放端口", "risk": "safe"},
        ],
        "先确认服务是否启动，再确认端口是否监听。如果服务未启动，使用 systemctl start 启动服务；如果端口未开放，需要检查 firewalld、iptables 或云服务器安全组。",
        "warning",
    ),
    (
        [
            "disk full",
            "no space left",
            "no space left on device",
            "磁盘空间不足",
            "空间不足",
            "device上没有剩余空间",
        ],
        "磁盘空间已满",
        "磁盘容量或 inode 耗尽，导致系统无法继续写入文件，常见于日志文件过大、Docker 镜像过多或临时文件未清理。",
        [
            {"cmd": "df -h", "desc": "查看各分区磁盘容量使用情况", "risk": "safe"},
            {"cmd": "df -i", "desc": "查看 inode 是否耗尽", "risk": "safe"},
            {"cmd": "du -sh /* --exclude=/proc 2>/dev/null", "desc": "查看根目录下各目录占用空间", "risk": "safe"},
            {"cmd": "find / -xdev -size +100M -exec ls -lh {} \\; 2>/dev/null", "desc": "查找超过 100MB 的大文件", "risk": "safe"},
            {"cmd": "docker system df", "desc": "查看 Docker 占用空间", "risk": "safe"},
        ],
        "优先清理无用日志、临时文件、过期备份和无用 Docker 镜像。生产环境不要直接删除不认识的文件，建议先确认文件用途，再进行清理或扩容磁盘。",
        "danger",
    ),
    (
        [
            "permission denied",
            "权限不足",
            "不允许的操作",
            "operation not permitted",
            "access denied",
            "拒绝访问",
        ],
        "权限不足",
        "当前用户或进程对目标文件、目录或命令没有足够权限，可能是文件属主、权限位、SELinux 或 sudo 权限导致。",
        [
            {"cmd": "ls -la <path>", "desc": "查看文件或目录权限和属主", "risk": "safe"},
            {"cmd": "id", "desc": "查看当前用户和所属用户组", "risk": "safe"},
            {"cmd": "sudo -l", "desc": "查看当前用户可执行的 sudo 命令", "risk": "safe"},
            {"cmd": "getenforce", "desc": "查看 SELinux 状态", "risk": "safe"},
        ],
        "根据实际情况使用 chmod 或 chown 修正权限，或者使用 sudo 执行命令。不要为了省事直接使用 chmod 777，生产环境可能造成安全风险。",
        "warning",
    ),
    (
        [
            "docker: command not found",
            "docker 未安装",
            "-bash: docker:",
            "command not found: docker",
        ],
        "Docker 未安装或环境变量异常",
        "系统没有安装 Docker，或者 Docker 命令不在 PATH 环境变量中。",
        [
            {"cmd": "which docker", "desc": "检查 docker 命令是否存在", "risk": "safe"},
            {"cmd": "docker --version", "desc": "查看 Docker 版本", "risk": "safe"},
            {"cmd": "systemctl status docker", "desc": "查看 Docker 服务状态", "risk": "safe"},
        ],
        "如果未安装 Docker，需要根据系统版本安装 Docker；如果已经安装但服务未启动，可以执行 systemctl start docker 启动服务。",
        "info",
    ),
    (
        [
            "container exited",
            "容器已退出",
            "exited with code",
            "状态 exited",
            "container 状态不是 up",
        ],
        "Docker 容器异常退出",
        "容器内主进程退出、配置错误、镜像启动命令错误、资源不足或程序崩溃都会导致容器退出。",
        [
            {"cmd": "docker ps -a", "desc": "查看所有容器状态", "risk": "safe"},
            {"cmd": "docker logs 容器名或容器ID --tail 100", "desc": "查看容器最近日志", "risk": "safe"},
            {"cmd": "docker inspect 容器名或容器ID", "desc": "查看容器详细信息", "risk": "safe"},
        ],
        "先通过 docker logs 查看容器退出原因。如果是配置错误，修改配置后重新启动；如果是内存不足，需要调整资源限制或优化程序。",
        "warning",
    ),
    (
        [
            "502 bad gateway",
            "504 gateway timeout",
            "upstream timed out",
            "upstream prematurely closed",
            "nginx 502",
            "nginx 504",
        ],
        "Nginx 网关错误",
        "Nginx 无法正常访问后端服务，常见原因是后端服务未启动、端口配置错误、后端响应超时或 upstream 配置错误。",
        [
            {"cmd": "systemctl status <service>", "desc": "检查后端服务是否运行", "risk": "safe"},
            {"cmd": "ss -tlnp | grep <PORT>", "desc": "检查后端端口是否监听", "risk": "safe"},
            {"cmd": "curl -I http://127.0.0.1:<backend-port>/", "desc": "本地测试后端服务是否响应", "risk": "safe"},
            {"cmd": "tail -100 /var/log/nginx/error.log", "desc": "查看 Nginx 错误日志", "risk": "safe"},
            {"cmd": "nginx -t", "desc": "检查 Nginx 配置语法", "risk": "safe"},
        ],
        "确认后端服务正常运行，并检查 Nginx upstream 地址和端口是否正确。如果是超时问题，可以适当调整 proxy_connect_timeout 和 proxy_read_timeout。",
        "danger",
    ),
    (
        [
            "404 not found",
            "nginx 404",
            "文件找不到",
            "no such file or directory",
        ],
        "资源不存在或路径错误",
        "请求的文件、接口路由或 Nginx root/alias 配置不正确，导致服务器找不到资源。",
        [
            {"cmd": "ls -la <web-root>/<path>", "desc": "检查目标文件是否存在", "risk": "safe"},
            {"cmd": "nginx -t", "desc": "检查 Nginx 配置语法", "risk": "safe"},
            {"cmd": "grep -r 'root\\|alias\\|try_files' /etc/nginx/ 2>/dev/null", "desc": "查看 Nginx 路径相关配置", "risk": "safe"},
        ],
        "检查访问路径是否正确，确认文件是否存在。如果是前端项目，需要检查 root、alias、try_files 配置是否正确。",
        "info",
    ),
    (
        [
            "oomkilled",
            "oom-kill",
            "out of memory",
            "内存溢出",
            "killed by oom",
        ],
        "进程或容器因内存不足被终止",
        "系统内存不足或容器内存限制过低，内核触发 OOM Killer，导致进程被强制杀死。",
        [
            {"cmd": "dmesg | grep -i 'oom' | tail -20", "desc": "查看内核 OOM 日志", "risk": "safe"},
            {"cmd": "free -h", "desc": "查看系统内存使用情况", "risk": "safe"},
            {"cmd": "top", "desc": "查看当前占用内存较高的进程", "risk": "safe"},
            {"cmd": "docker stats --no-stream", "desc": "查看 Docker 容器资源使用情况", "risk": "safe"},
        ],
        "可以增加内存或 swap，优化程序内存占用，或者调整容器内存限制。生产环境需要先判断是否存在内存泄漏。",
        "danger",
    ),
    (
        [
            "port already in use",
            "port is already allocated",
            "地址已在使用",
            "address already in use",
            "端口被占用",
            "bind: address already in use",
            "failed: port is already",
        ],
        "端口冲突",
        "要绑定的端口已经被其他进程或容器占用，导致当前服务无法启动或无法映射端口。",
        [
            {"cmd": "ss -tlnp | grep <PORT>", "desc": "查看端口被哪个进程占用", "risk": "safe"},
            {"cmd": "lsof -i<PORT>", "desc": "查看占用该端口的进程详情", "risk": "safe"},
            {"cmd": "ps aux | grep <PID>", "desc": "查看占用端口的进程信息", "risk": "safe"},
            {"cmd": "docker ps -a", "desc": "如果是 Docker 端口冲突，查看容器端口映射", "risk": "safe"},
        ],
        "可以修改当前服务监听端口，或者停止占用该端口的进程/容器。停止进程前必须确认该进程是否属于重要业务。",
        "info",
    ),
    (
        [
            "crashloopbackoff",
            "back-off restarting failed container",
        ],
        "Kubernetes Pod 反复重启",
        "Pod 内容器启动后不断崩溃，Kubernetes 按退避策略反复重启容器。",
        [
            {"cmd": "kubectl get pods", "desc": "查看 Pod 当前状态", "risk": "safe"},
            {"cmd": "kubectl describe pod Pod名称", "desc": "查看 Pod 事件和异常原因", "risk": "safe"},
            {"cmd": "kubectl logs Pod名称", "desc": "查看当前容器日志", "risk": "safe"},
            {"cmd": "kubectl logs Pod名称 --previous", "desc": "查看上一次崩溃前的日志", "risk": "safe"},
        ],
        "重点查看容器日志和 describe 事件，常见原因包括启动命令错误、配置文件错误、环境变量缺失、依赖服务不可用或健康检查失败。",
        "warning",
    ),
    (
        [
            "imagepullbackoff",
            "errimagepull",
            "pull access denied",
        ],
        "Kubernetes 镜像拉取失败",
        "Kubernetes 无法拉取容器镜像，可能是镜像名错误、仓库无权限、网络异常或 imagePullSecret 配置错误。",
        [
            {"cmd": "kubectl get pods", "desc": "查看 Pod 状态", "risk": "safe"},
            {"cmd": "kubectl describe pod Pod名称", "desc": "查看镜像拉取失败的详细事件", "risk": "safe"},
            {"cmd": "docker pull 镜像名称", "desc": "在节点上测试是否可以手动拉取镜像", "risk": "safe"},
        ],
        "检查镜像名称、tag、仓库地址和认证信息。如果是私有仓库，需要配置 imagePullSecret。",
        "warning",
    ),
]


def _match_local(log_text):
    """
    在本地知识库中匹配关键词。
    命中后返回结构化结果，并自动替换命令里的端口、服务名等占位符。
    """
    log_lower = log_text.lower()

    for keywords, fault_type, cause, commands, solution, risk in LOCAL_KB:
        for kw in keywords:
            if kw.lower() in log_lower:
                return normalize_result({
                    "fault_type": fault_type,
                    "cause": cause,
                    "commands": fill_placeholders(commands, log_text),
                    "solution": solution,
                    "risk_level": risk,
                })

    return None


# =========================
# DeepSeek API
# =========================

SYSTEM_PROMPT = """
你是一个专业的 Linux / Docker / Nginx / Kubernetes 云计算运维故障排查助手。

用户会输入报错日志或异常描述。
你需要分析故障类型、原因、排查命令、解决方案和风险等级。

你必须严格按照以下 JSON 格式返回，不要输出 Markdown，不要输出代码块，不要输出其他解释：

{
  "fault_type": "故障类型，用中文简短概括",
  "cause": "故障原因分析，80-180字，中文，适合初学者理解",
  "commands": [
    {
      "cmd": "具体排查命令",
      "desc": "命令用途",
      "risk": "safe"
    }
  ],
  "solution": "解决方案，100-250字，中文，尽量分步骤说明",
  "risk_level": "safe"
}

字段要求：
1. fault_type 必须是中文。
2. commands 至少返回 2 条命令。
3. commands 中的 risk 只能是 safe、warning、danger。
4. risk_level 只能是 safe、info、warning、danger。
5. 如果日志中有具体端口号，例如 80、8080、3306，命令里必须直接使用具体端口号。
6. 不要输出 <PORT>、<PID>、<container>、<pod> 这种占位符。
7. 如果不知道具体 PID，请写“实际进程PID”，并说明需要先通过 ss 或 lsof 查询。
8. 如果是端口冲突，优先给出 ss、lsof、docker ps -a。
9. 如果是磁盘满，优先给出 df -h、df -i、du -sh。
10. 如果是权限问题，优先给出 ls -la、id、sudo -l。
11. 如果是 Docker 问题，优先给出 docker ps -a、docker logs、docker inspect。
12. 如果是 Kubernetes 问题，优先给出 kubectl get pods、kubectl describe pod、kubectl logs。
13. 不要建议用户直接执行 rm -rf、chmod 777、kill -9、docker rm、kubectl delete，除非明确说明风险。
14. 如果无法判断，fault_type 返回“无法识别”，并给出通用排查建议。
"""


def _call_deepseek(log_text):
    """
    调用 DeepSeek API 分析日志。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")

    if not api_key or api_key == "sk-your-key-here":
        return normalize_result({
            "fault_type": "API 未配置",
            "cause": "当前项目没有读取到有效的 DEEPSEEK_API_KEY，无法调用 DeepSeek API。",
            "commands": [
                {"cmd": "ls -a", "desc": "查看项目目录下是否存在 .env 文件", "risk": "safe"},
                {"cmd": "grep '^DEEPSEEK_API_KEY=' .env", "desc": "检查 .env 中是否配置了 API Key，注意不要把 Key 截图发给别人", "risk": "safe"},
            ],
            "solution": "在项目根目录创建 .env 文件，写入 DEEPSEEK_API_KEY=你的DeepSeek_API_Key，然后重新启动 uvicorn 服务。",
            "risk_level": "info",
        })

    url = "{}/v1/chat/completions".format(base_url)

    ports = extract_ports(log_text)
    service = extract_service_name(log_text)

    user_prompt = """
请分析以下报错日志：

日志内容：

自动识别信息：
- 端口号：{}
- 相关服务：{}

请返回严格 JSON。
""".format(
        log_text,
        "、".join(ports) if ports else "未识别到明确端口",
        service,
    )

    headers = {
        "Authorization": "Bearer {}".format(api_key),
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

    except requests.exceptions.Timeout:
        return normalize_result({
            "fault_type": "AI 接口请求超时",
            "cause": "服务器请求 DeepSeek API 超时，可能是网络较慢、API 响应较慢或输入内容过长。",
            "commands": [
                {"cmd": "curl -I https://api.deepseek.com", "desc": "测试服务器是否能访问 DeepSeek API", "risk": "safe"},
                {"cmd": "ping api.deepseek.com", "desc": "测试网络连通性", "risk": "safe"},
            ],
            "solution": "可以稍后重试，或者缩短输入日志内容后重新分析。如果服务器无法访问外网，需要检查网络、防火墙或代理配置。",
            "risk_level": "info",
        })

    except Exception as e:
        return normalize_result({
            "fault_type": "API 调用异常",
            "cause": "DeepSeek API 请求失败：{}".format(str(e)),
            "commands": [
                {"cmd": "curl -I https://api.deepseek.com", "desc": "测试 DeepSeek API 访问情况", "risk": "safe"},
                {"cmd": "grep '^DEEPSEEK_API_KEY=' .env", "desc": "检查 API Key 是否配置，注意不要泄露 Key", "risk": "safe"},
            ],
            "solution": "请检查网络连通性、API Key 是否正确、API 账户状态以及服务器是否可以访问外网。",
            "risk_level": "info",
        })

    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if json_match:
        content = json_match.group()

    try:
        result = json.loads(content)
        return normalize_result(result)

    except json.JSONDecodeError:
        return normalize_result({
            "fault_type": "AI 返回格式异常",
            "cause": "DeepSeek 返回的内容不是标准 JSON，导致程序无法解析。",
            "commands": [
                {"cmd": "journalctl -xe --no-pager | tail -50", "desc": "查看系统最近错误日志", "risk": "safe"},
                {"cmd": "dmesg | tail -20", "desc": "查看内核最近日志", "risk": "safe"},
            ],
            "solution": "可以重新点击分析，或补充更完整的日志内容。如果经常出现该问题，需要继续优化 SYSTEM_PROMPT。",
            "risk_level": "info",
        })


def analyze_log(log_text):
    """
    分析日志入口。
    返回格式必须是字典：
    {
      "fault_type": "...",
      "cause": "...",
      "commands": [...],
      "solution": "...",
      "risk_level": "..."
    }
    """
    if not log_text or not log_text.strip():
        return normalize_result({
            "fault_type": "输入为空",
            "cause": "用户没有输入需要分析的日志或问题。",
            "commands": [],
            "solution": "请在输入框中粘贴 Linux、Nginx、Docker、Kubernetes 等报错日志后再点击分析。",
            "risk_level": "info",
        })

    log_text = log_text.strip()

    # 1. 优先匹配本地知识库
    local_result = _match_local(log_text)
    if local_result:
        return local_result

    # 2. 本地知识库未命中，再调用 DeepSeek
    return _call_deepseek(log_text)
