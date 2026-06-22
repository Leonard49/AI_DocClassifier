#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多层级标签树 LLM 文本分类器（OpenAI 兼容 API）
输出 JSON 格式，例如 {"tag1": ["Cellular"], "tag2": ["4G network"]}
模型与网关通过环境变量 LLM_MODEL / LLM_BASE_URL 配置。
"""

import os
import json
import random
import re
import time
from typing import Dict, List, Union, Optional, Tuple, TYPE_CHECKING

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from llm_rate_limit import LLM_CONCURRENCY, LLM_RATE_LIMITER

if TYPE_CHECKING:
    from classify_cache import ClassifyCache

RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})

DEFAULT_LLM_BASE_URL = "https://qlitellm.phicotek.com/v1"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"


class LLMTreeClassifier:
    """使用 OpenAI 兼容 API 对文本进行多层级标签树分类，输出 JSON 格式的路径"""

    REFINEMENT_ALIASES = {
        ("Smart -> BSP", "LCD/TP"): ["lcd", "tp", "touch panel", "display", "mipi", "屏", "触摸", "lt8912", "hdmi"],
        ("Smart -> BSP", "Camera"): ["camera", "摄像", "imx", "ov", "sensor camera"],
        ("Smart -> BSP", "Sensor"): ["sensor", "accel", "gyro", "gsensor", "als", "psensor"],
        ("Smart -> BSP", "GPIO"): ["gpio", "pin", "pinctrl"],
        ("Smart -> BSP", "Audio"): ["audio", "mic", "speaker", "codec", "i2s", "acdb", "mixer", "录音"],
        ("Smart -> BSP", "I2C/UART/SPI/CAN"): [
            "i2c", "uart", "spi", "can", "serial", "rtc", "字符设备",
            "character device", "device driver",
        ],
        ("Smart -> BSP", "USB"): ["usb", "adb", "type-c", "typec"],
        ("Smart -> BSP", "SD CARD/SIM"): [
            "sd card", "sdcard", "tf card", "sim card", "sdio",
            "nand", "emmc", "flash", "partition", "ecc",
            "ddr", "emi", "ett", "memory",
        ],
        ("Smart -> BSP", "Fuel guage/Charging/NTC"): ["fuel", "gauge", "guage", "charging", "charger", "battery", "ntc", "电池", "充电"],
        ("Smart -> BSP", "ETH/NFC/WiFi"): [
            "eth", "ethernet", "nfc", "wifi", "wi-fi", "wlan", "wpa",
            "hostapd", "bluetooth", "blue tooth", "蓝牙",
        ],
        ("Smart -> System", "OTA"): ["ota", "fota", "dfota", "upgrade", "升级"],
        ("Smart -> System", "SELinux"): ["selinux", "sepolicy", "avc denied"],
        ("Smart -> System", "Secureboot"): ["secureboot", "secure boot", "verity", "dm-verity"],
        ("Smart -> System", "系统优化"): [
            "optimization", "optimize", "性能", "优化", "memory", "内存",
            "storage", "权限", "iptables", "git", "boot", "启动", "adb",
            "root", "unpacking", "代码下载", "系统启动", "分区", "重启",
            "rescueparty", "qfil", "non-hlos", "repository", "repo",
            "compile", "编译", "烧录",
        ],
        ("Smart -> System", "Thermal"): ["thermal", "temperature", "温度", "过热"],
        ("Smart -> Yocto", "yocto 系统自启动"): ["autostart", "auto start", "自启动", "开机启动", "systemd"],
        ("Smart -> Yocto", "yocto 应用内置"): ["内置", "preinstall", "built-in"],
        ("Smart -> Yocto", "yocto 系统优化&裁剪"): [
            "裁剪", "overlay", "partition", "rootfs", "优化",
            "ubuntu", "linux", "bitbake", "oe-core", "sdk编译", "sdk 编译",
            "system compilation", "build_wf", "permission denied",
            "toolchain", "工具链", "环境搭建", "compile error", "root用户",
        ],
        ("Smart -> Yocto", "yocto APP开发"): ["app", "application", "应用开发", "gstreamer", "gst"],
        ("Smart -> Yocto", "yocto 第三方工具集成"): ["docker", "opencv", "mediapipe", "third party", "第三方"],
        ("Smart -> BP", "XBL"): ["xbl", "edk2", "uefi", "bootloader"],
        ("Smart -> BP", "TZ"): ["tz", "trustzone", "qsee"],
        ("Cellular -> Network", "LPWA Network"): ["lpwa", "nb-iot", "nbiot", "cat.m", "cat-m", "emtc"],
        ("Cellular -> Network", "LTE Network"): [
            "lte", "4g", "cat1", "cat.1", "gsm", "wcdma", "2g",
            "rrc", "attach", "rplmn", "edrx", "rat", "mtu", "9x07",
            "8910", "register", "registration", "network", "注网",
            "网络", "漫游", "timer", "掉网",
        ],
        ("Cellular -> Network", "5G Network"): ["5g", "nr", "sa", "nsa"],
        ("Cellular -> 网卡拨号", "ECM"): ["ecm", "eth0"],
        ("Cellular -> 网卡拨号", "QMI"): ["qmi", "quectel-cm", "qmi_wwan", "gobinet"],
        ("Cellular -> 网卡拨号", "MBIM"): ["mbim"],
        ("Cellular -> 网卡拨号", "RNDIS"): ["rndis"],
        ("Cellular -> 网卡拨号", "RMNET"): [
            "rmnet", "qcmap", "multi-data-call", "multi data call",
            "data-call", "vlan", "ippt", "wan", "route/ippt", "多路拨号",
            "route", "default route", "default.script", "dhcp", "获取ip",
            "ip地址", "路由模式", "拨号成功", "linux拨号", "网卡路由",
        ],
        ("Cellular -> SIM Card", "USIM"): [
            "usim", "sim", "iccid", "imsi", "imei", "meid", "mcc", "mnc",
            "fplmn", "rplmn", "stk", "crsm", "dsss", "卡槽", "切卡",
            "无卡", "psm", "供电", "sim卡",
        ],
        ("Cellular -> SIM Card", "eSIM"): ["esim", "e-sim"],
        ("Cellular -> SIM Card", "iSIM"): ["isim", "i-sim"],
        ("Cellular -> SIM Card", "vSIM"): ["vsim", "v-sim"],
        ("QuecOpen -> 快速入门&FAQ", "SDK介绍及编译"): ["sdk", "compile", "编译", "integration", "hal"],
        ("QuecOpen -> 快速入门&FAQ", "固件升级"): ["upgrade", "升级", "dfota", "fota"],
        ("QuecOpen -> 快速入门&FAQ", "Log抓取"): ["log", "日志"],
        ("QuecOpen -> 快速入门&FAQ", "开发调试相关"): ["debug", "调试", "入门"],
        ("QuecOpen -> 平台和系统", "Secure Boot"): [
            "isolated user", "user environment", "有限目录", "访问有限",
            "权限", "passwd", "shadow", "secure", "security", "安全",
        ],
        ("QuecOpen -> 平台和系统", "Dfota"): ["dfota", "fota", "upgrade", "升级"],
        ("QuecOpen -> 平台和系统", "性能优化"): [
            "performance", "性能", "优化", "partition", "分区", "filesystem",
            "file system", "文件系统", "ubi", "mtd", "squashfs", "rootfs",
            "glibc", "开机启动", "boot", "logo",
        ],
        ("QuecOpen -> 常见外设接口及驱动", "GPIO"): ["gpio", "adc", "watchdog", "看门狗"],
        ("QuecOpen -> 常见外设接口及驱动", "I2C/UART/SPI"): ["i2c", "uart", "spi"],
        ("QuecOpen -> 常见外设接口及驱动", "USB"): ["usb"],
        ("QuecOpen -> 常见外设接口及驱动", "I2S"): ["i2s"],
        ("QuecOpen -> 常见外设接口及驱动", "SDIO"): ["sdio", "emmc", "sd card", "sdcard"],
        ("QuecOpen -> 常见外设接口及驱动", "SGMII"): ["sgmii", "网口", "ethernet", "网卡"],
        ("QuecOpen -> 常见外设接口及驱动", "设备树"): [
            "设备树", "device tree", "devicetree", "dts", "dtsi", "insmod", ".ko",
        ],
        ("QuecOpen -> 数据拨号", "Open API拨号"): ["open api", "api拨号", "默认路由", "default route"],
        ("QuecOpen -> 数据拨号", "PPP拨号"): ["ppp"],
        ("QuecOpen -> 数据拨号", "USB上网及拨号工具"): ["usb", "拨号工具"],
        ("QuecOpen -> 设备及网络管理", "网络状态获取及说明"): [
            "network management", "网络管理", "mac", "vlan", "lan", "ip地址",
            "qlril", "api-test", "网络状态",
        ],
        ("QuecOpen -> 设备及网络管理", "网络注册步骤及常见问题分析"): ["注册", "驻网", "attach"],
        ("QuecOpen -> 设备及网络管理", "SIM使用及管理"): ["sim"],
        ("QuecOpen -> Linux应用", "MQTT"): ["mqtt"],
        ("QuecOpen -> Linux应用", "HTTP"): ["http"],
        ("QuecOpen -> Linux应用", "FTP"): ["ftp"],
        ("QuecOpen -> Linux应用", "时间系统"): ["time", "时间", "rtc", "ntp"],
        ("QuecOpen -> Linux应用", "LWM2M"): ["lwm2m"],
        ("QuecOpen -> Linux应用", "应用日志管理"): ["log", "日志"],
        ("QuecOpen -> Linux应用", "QMI&MCM接口"): ["qmi", "mcm", "urc"],
        ("QuecOpen -> RTOS系统及应用", "MQTT"): ["mqtt"],
        ("QuecOpen -> RTOS系统及应用", "HTTP"): ["http"],
        ("QuecOpen -> RTOS系统及应用", "FTP"): ["ftp"],
        ("QuecOpen -> RTOS系统及应用", "LWM2M"): ["lwm2m"],
        ("QuecOpen -> RTOS系统及应用", "应用日志"): ["log", "日志", "timer"],
        ("Cellular -> 通信接口", "UART"): ["uart", "ri", "urc", "at指令", "at command"],
        ("Cellular -> 通信接口", "USB"): ["usb"],
        ("Cellular -> 通信接口", "PCIE"): ["pcie", "pci-e"],
        ("Cellular -> 通信接口", "CMUX"): ["cmux"],
        ("Cellular -> 认证", "FCC"): ["fcc"],
        ("Cellular -> 认证", "AT&T"): ["at&t"],
        ("Cellular -> 认证", "Verizon"): ["verizon"],
        ("周会通", "会议纪要"): ["会议", "meeting", "纪要"],
        ("周会通", "周报"): ["周报", "weekly", "重点客户", "工作分享"],
        ("周会通", "通知类"): ["通知", "notice"],
        ("Antenna", "PCB Antenna"): ["pcb"],
    }

    # ============================================================
    # 预定义标签树（唯一数据源）
    # ============================================================
    LABEL_TREE = {
        "Cellular": {
            "驱动": {},
            "固件升级": {},
            "FOTA": {},
            "LOG抓取": {},
            "Flash备份还原": {},
            "Security Feature": {},
            "通信接口": {
                "UART": [], "USB": [], "PCIE": [], "CMUX": []
            },
            "Network": {
                "LPWA Network": [], "LTE Network": [], "5G Network": []
            },
            "NTN": {},
            "D2C": {},
            "SIM Card": {
                "USIM": [], "eSIM": [], "vSIM": [], "iSIM": []
            },
            "Audio": {},
            "Voice Call": {},
            "SMS": {},
            "TCP&UDP": {},
            "SSL": {},
            "HTTP(S)": {},
            "MQTT(S)": {},
            "FTP(S)": {},
            "CoAP(S)": {},
            "LWM2M": {},
            "WebSocket": {},
            "SMTP": {},
            "MMS": {},
            "PPP": {},
            "网卡拨号": {
                "ECM": [], "QMI": [], "MBIM": [], "RNDIS": [], "RMNET": []
            },
            "低功耗": {},
            "File": {},
            "GNSS": {},
            "WIFI": {},
            "蓝牙": {},
            "FTM": {},
            "认证": {
                "PTCRB": [], "FCC": [], "Verizon": [], "T-Mobile": [], 
                "AT&T": [], "Vodafone": [], "Telstra": [], "Softbank": [], "SIRIM": []
            },
            "竞品分析": {},
            "行业分析": {},
            "BB": {},
            "RF": {},
            "Antenna": {},
            "ECM": {},
        },
        "Automotive": {
            "BB": {},
            "RF": {},
            "Antenna": {},
            "EMC": {},
            "产品介绍": {},
            "工具": {},
            "编译": {},
            "接口": {},
            "功能验证": {
                "SDK Compile": [], "Sleep Mode": [], "Data Call Function": [], 
                "USB Driver": [], "Common Peripheral Function": [],
                "Low Power Mode Issue Analysis": [], 
                "Secboot": {"bussiness license": []}, 
                "ECall": [], "WI-FI Related Knowledge": [], "V2X": [], 
                "QDR": [], "GNSS": []
            },
            "认证": {},
            "竞品分析": {},
            "行业分析": {},
        },
        "Smart": {
            "HW": {"EVB": [], "Logic Analyzer": [], "Oscilloscope": []},
            "BSP": {
                "LCD/TP": [], "Camera": [], "Sensor": [],
                "GPIO": [], "Audio": [], "I2C/UART/SPI/CAN": [],
                "USB": [], "SD CARD/SIM": [],
                "Fuel guage/Charging/NTC": [], "ETH/NFC/WiFi": []
            },
            "BP": {
                "XBL": [], "TZ": []
            },
            "AI": {
                "高通 SNPE": [], "瑞芯微 RKNN": []
            },
            "调试方案": {
                "充电方案": [], "外挂模组(GNSS.Cellular/WIFI,Ethernet)": []
            },
            "平台安全": {},
            "多媒体": {"video": [], "Audio": []},
            "FrameWork": {},
            "Andriod APP": {},
            "认证": {},
            "BB": {},
            "RF": {},
            "竞品分析报告": {},
            "行业分析报告": {},
            "Antenna": {},
            "EMC": {},
            "System": {
                "OTA": [], "Thermal": [], "SELinux": [],
                "Secureboot": [], "系统优化": []
            },
            "Yocto": {
                "yocto APP开发": [], "yocto 应用内置": [], "yocto 第三方工具集成": [],
                "yocto 系统自启动": [], "yocto 系统优化&裁剪": []
            }
        },
        "ShortRange": {
            "MCU WIFI": [], "RF WIFI": [], "Bluetooth": [], "Matter": [], 
            "Lora": [], "Zigbee": [], "Wisun": [], "M-Bus": [], "Halow": [], 
            "UWB": [], "抓log": [], "Log分析": [], "射频测试": [], "认证": [], 
            "打流速率": [], "硬件原理": [], "竞品报告": [], "Driver bing up": [], 
            "Host test user guide": [], "AT command": []
        },
        "GNSS": {
            "GNSS功能原理": {
                "RTK": [], "PPP": [], "DR": []
            },
            "GNSS产品介绍": {},
            "GNSS硬件": {},
            "GNSS软件": {},
            "GNSS射频": {},
            "GNSS测试": {},
            "竞品报告": {},
            "行业分析": {},
            "GNSS问题分析": {"失效分析": [], "GNSS FAQ": [], "典型问题分析": []},
            "GNSS标准协议解读": {
                "NEMA协议解读": [], "RTCM协议解读": [], "RINEX协议解读": [],
                "ECall认证解读": [], "CarPlay认证解读": [], "Android Auto认证解读": [],
                "GB 45086车载定位系统规范": []
            },
            "GNSS工具应用指导": {"QGNSS应用指导": [], "RTKLIB应用指导": []},
            "GNSS分析方法": {"Debug Log": [], "固件回读": []},
            "GNSS示例代码": {"升级示例代码": [], "AGNSS示例代码": []},
            "GNSS FAE工作流程": {}
        },
        "QuecOpen": {
            "快速入门&FAQ": {
                "SDK介绍及编译": [], "固件升级": [], "Log抓取": [], "开发调试相关": []
            },
            "数据拨号": {
                "USB上网及拨号工具": [], "PPP拨号": [], "Open API拨号": []
            },
            "平台和系统": {
                "Dfota": [], "Secure Boot": [], "性能优化": [], "GNSS": [],
                "WI-FI": [], "BlueTooth": []
            },
            "设备及网络管理": {
                "网络状态获取及说明": [], "网络注册步骤及常见问题分析": [],
                "SIM使用及管理": []
            },
            "音频及语音通话": {
                "普通语音通话": [], "录音及播音": [], "Codec及相关及硬件": [],
                "USB音频(UAC)": [], "音频参数调整及ACDB": []
            },
            "电源及功耗管理": {
                "开关机相关": [], "低功耗应用": [], "功耗测量": []
            },
            "常见外设接口及驱动": {
                "GPIO": [], "I2C/UART/SPI": [], "SDIO": [], "USB": [], 
                "I2S": [], "SGMII": [], "设备树": []
            },
            "Linux应用": {
                "HTTP": [], "MQTT": [], "FTP": [], "时间系统": [], 
                "LWM2M": [], "应用日志管理": [], "QMI&MCM接口": []
            },
            "RTOS系统及应用": {
                "HTTP": [], "MQTT": [], "FTP": [], "LWM2M": [], "应用日志": []
            }
        },
        "Satellite": {
            "IoT NTN": {},
            "NR NTN": {},
            "Startlink": {}
        },
        "Antenna": {
            "FPC Antenna": [], "LDS Antenna": [], "PCB Antenna": [],
            "SMD / Chip Antenna": [], "Ceramic Antenna": [], "Metal Stamped Antenna": [],
            "Spring Antenna": [], "Pogo Pin / Contact Pin Antenna": [],
            "External Antenna": [], "On-board Antenna": [], "NFC Antenna": []
        },
        "Services": {},
        "失效分析": {
            "典型案例": {},
            "技术文档": {"5G": [], "Smart": [], "LTE": [], "NB": [], "PCBA": [], "WIFI&BT": []}
        },
        "周会通": {"周报": [], "会议纪要": [], "通知类": []},
        "Others": {}
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_content_chars: int = 3000,
        verbose: bool = True,
        cache: Optional["ClassifyCache"] = None,
        max_retries: int = 6,
        request_timeout: float = 120.0,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("请设置有效的 LLM API Key（环境变量 LLM_API_KEY）")
        self.model = model or DEFAULT_LLM_MODEL
        self.base_url = base_url or DEFAULT_LLM_BASE_URL
        # 关闭 SDK 内置短间隔重试，避免 4 路并发时同时打出大量 502 重试
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=0,
            timeout=request_timeout,
        )
        self.max_content_chars = max_content_chars
        self.verbose = verbose
        self.cache = cache
        self.max_retries = max_retries

        # Precompute all paths and leaf-only paths. Classification is considered
        # complete only when the selected path has no child category.
        self.all_paths = self._extract_all_paths(self.LABEL_TREE)
        self.leaf_paths = self._extract_leaf_paths(self.LABEL_TREE)
        self.valid_paths = self.leaf_paths
        self.root_labels = list(self.LABEL_TREE.keys())
        
        # 生成标签树描述（自动从 LABEL_TREE 生成，无需手动维护）
        self.tree_description = self._generate_tree_description()
        self.prompt_template = self._build_prompt_template()

    def _extract_all_paths(self, tree: Union[Dict, List], prefix: str = "") -> List[str]:
        """递归提取所有可能的路径"""
        paths = []
        if isinstance(tree, dict):
            for key, value in tree.items():
                current = f"{prefix} -> {key}" if prefix else key
                paths.append(current)
                if isinstance(value, dict) and value:  # 非空字典
                    paths.extend(self._extract_all_paths(value, current))
                elif isinstance(value, list) and value:  # 非空列表
                    for item in value:
                        paths.append(f"{current} -> {item}")
        elif isinstance(tree, list):
            for item in tree:
                paths.append(f"{prefix} -> {item}" if prefix else item)
        return paths

    def _extract_leaf_paths(self, tree: Union[Dict, List], prefix: str = "") -> List[str]:
        """Return only paths that have no child category."""
        paths = []
        if isinstance(tree, dict):
            for key, value in tree.items():
                current = f"{prefix} -> {key}" if prefix else key
                if isinstance(value, dict) and value:
                    paths.extend(self._extract_leaf_paths(value, current))
                elif isinstance(value, list) and value:
                    for item in value:
                        paths.append(f"{current} -> {item}")
                else:
                    paths.append(current)
        elif isinstance(tree, list):
            for item in tree:
                paths.append(f"{prefix} -> {item}" if prefix else item)
        return paths

    def _is_leaf_path(self, path_str: str) -> bool:
        return path_str == "Others" or path_str in self.leaf_paths

    def _leaf_descendants(self, parent_path: str) -> List[str]:
        prefix = f"{parent_path} -> "
        return [path for path in self.leaf_paths if path.startswith(prefix)]

    def _keyword_refine_leaf(
        self,
        parent_path: str,
        candidates: List[str],
        user_text: str,
    ) -> Optional[str]:
        text = (user_text or "").lower()
        scores = {}
        for candidate in candidates:
            label = candidate.split(" -> ")[-1]
            candidate_parent = " -> ".join(candidate.split(" -> ")[:-1])
            custom_aliases = (
                self.REFINEMENT_ALIASES.get((parent_path, label), [])
                + self.REFINEMENT_ALIASES.get((candidate_parent, label), [])
            )
            aliases = [label] + custom_aliases
            for index, alias in enumerate(aliases):
                alias_norm = alias.lower().strip()
                if alias_norm and alias_norm in text:
                    scores[candidate] = scores.get(candidate, 0) + (1 if index == 0 else 2)
        if scores:
            best_score = max(scores.values())
            best_matches = sorted(path for path, score in scores.items() if score == best_score)
            if len(best_matches) == 1:
                return best_matches[0]
        return None

    def _tag_to_path(self, tag: Dict[str, List[str]]) -> str:
        parts = []
        idx = 1
        while True:
            value = tag.get(f"tag{idx}")
            if not value:
                break
            parts.append(value[0])
            idx += 1
        return " -> ".join(parts)

    def _build_messages(self, prompt: str) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "你是一个专业的技术文档分类专家。严格按照分类规则输出，不添加任何额外内容。",
            },
            {"role": "user", "content": prompt},
        ]

    def _generate_tree_description(self) -> str:
        """从 LABEL_TREE 自动生成标签树描述文本"""
        lines = []
        
        def format_tree(node: Union[Dict, List], indent: int = 0, prefix: str = ""):
            """递归格式化树结构"""
            if isinstance(node, dict):
                for key, value in node.items():
                    # 添加当前节点
                    if indent == 0:
                        lines.append(f"- {key}:")
                    else:
                        spaces = "  " * indent
                        if isinstance(value, dict) and value:
                            lines.append(f"{spaces}- {key}:")
                        else:
                            lines.append(f"{spaces}- {key}")
                    
                    # 递归处理子节点
                    if isinstance(value, dict) and value:
                        format_tree(value, indent + 1, key)
                    elif isinstance(value, list) and value:
                        # 处理列表类型的子节点
                        spaces = "  " * (indent + 1)
                        items_str = "、".join(value)
                        lines.append(f"{spaces}  {items_str}")
            
            elif isinstance(node, list):
                # 处理列表节点
                if node:
                    spaces = "  " * indent
                    items_str = "、".join(node)
                    lines.append(f"{spaces}{items_str}")
        
        format_tree(self.LABEL_TREE)
        return "\n".join(lines)

    def _build_prompt_template(self) -> str:
        """构建完整的提示模板"""
        return f"""你是一个文档内容分析专家，请严格遵守"层级标签树"的标签类型，分析文档中的内容将内容按照标签类型进行精确归类。

你的任务：从下面给定的标签树中，选择**唯一一条最合理的最底层叶子路径**。

====================
【标签树（必须严格遵守）】
{self.tree_description}
====================

【最重要规则（必须严格遵守）】

1. 层级必须符合树结构（禁止错误层级）
   - "4G network" 和 "5G Network" 只能属于 Cellular 的子类
   - 错误："4G network"
   - 正确："Cellular -> 4G network"

2. 1层级必须要符合文章的整体适用范围或者大的方向，后续层级在1层级中选择合适的标签

3. 必须选择最底层叶子路径
   - 如果某个标签下面还有子标签，不能停在这个上层标签
   - 错误："Smart -> BSP"
   - 正确："Smart -> BSP -> Audio" 或 "Smart -> BSP -> GPIO" 等 BSP 下的叶子标签

4. 不允许"跳级"或"并列误用"
   - 如果选了子类，必须包含它的父类
   - 例如："5G Network" -> "Cellular -> 5G Network"

5. 只能输出一条路径（最匹配的一条）

6. 输出必须完全匹配树中的名称（大小写敏感）

7. 如果无法匹配，输出：Others

====================
【输出格式（严格，必须是叶子路径）】

只输出一行路径字符串，不要JSON，不要解释：

示例：
Cellular -> 5G Network
Smart -> BSP -> Audio
GNSS -> GNSS功能原理 -> RTK
Others

====================
【用户文本】
{{user_text}}

【分类结果】
"""

    def _build_prompt(self, user_text: str) -> str:
        """构建用户提示"""
        return self.prompt_template.format(user_text=user_text)

    def _build_refinement_prompt(self, parent_path: str, candidates: List[str], user_text: str) -> str:
        candidate_text = "\n".join(f"- {path}" for path in candidates)
        return f"""上一次分类结果只定位到了上层分类：{parent_path}

这个上层分类下面还有子分类，不能作为最终结果。请只从下面这些最底层叶子路径中选择唯一一个最匹配的路径。

====================
【可选叶子路径】
{candidate_text}
====================

要求：
1. 只能输出上面列表中的一整行路径。
2. 不要输出上层分类。
3. 不要解释，不要 JSON。
4. 如果确实无法匹配，输出：Others

【用户文本】
{user_text}
"""

    def _clean_response(self, text: str) -> str:
        """清理 AI 返回的文本，提取出路径字符串"""
        raw = text.strip()
        # 去除 markdown 代码块
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip().strip('"').strip("'")
        if raw.startswith("分类结果："):
            raw = raw.replace("分类结果：", "").strip()
        # 如果结果中包含换行，只取第一行（通常就是路径）
        if "\n" in raw:
            raw = raw.split("\n")[0].strip()
        raw = re.sub(r"^\s*[-*]\s*", "", raw)
        raw = re.sub(r"^\s*\d+[.)、]\s*", "", raw)
        raw = raw.replace("→", "->").replace("=>", "->")
        raw = re.sub(r"\s*->\s*", " -> ", raw)
        return raw

    def _path_to_json(self, path_str: str) -> Dict[str, List[str]]:
        """将路径字符串转换为 JSON 字典"""
        if path_str == "Others" or not path_str:
            return {"tag1": ["Others"]}
        # 按 " -> " 分割
        parts = [p.strip() for p in path_str.split(" -> ")]
        result = {}
        for i, part in enumerate(parts, start=1):
            result[f"tag{i}"] = [part]
        return result

    def _validate_path(
        self,
        path_str: str,
        *,
        candidate_paths: Optional[List[str]] = None,
        leaf_only: bool = False,
    ) -> str:
        """验证路径是否有效，无效则尝试修正或返回 Others"""
        if path_str == "Others":
            return path_str
        candidates = candidate_paths or (self.leaf_paths if leaf_only else self.all_paths)
        
        # 直接匹配
        if path_str in candidates:
            return path_str

        if leaf_only and path_str in self.all_paths:
            print(f"警告: 路径 '{path_str}' 不是最底层叶子路径")
            return "Others"
        
        # 尝试模糊匹配；候选必须唯一，避免把上层路径随意扩展到第一个叶子。
        fuzzy_matches = [
            valid for valid in candidates
            if path_str in valid or valid in path_str
        ]
        if len(fuzzy_matches) == 1:
            print(f"模糊匹配: '{path_str}' -> '{fuzzy_matches[0]}'")
            return fuzzy_matches[0]
        
        # 尝试部分匹配（只匹配最后一级）
        last_part = path_str.split(" -> ")[-1]
        partial_matches = [
            valid for valid in candidates
            if valid.endswith(f" -> {last_part}") or valid == last_part
        ]
        if len(partial_matches) == 1:
            print(f"部分匹配: '{path_str}' -> '{partial_matches[0]}'")
            return partial_matches[0]
        
        print(f"警告: 路径 '{path_str}' 不在预定义标签树中，回退为 Others")
        return "Others"

    def _request_path(self, prompt: str) -> str:
        response = self._chat_completion_with_retry(self._build_messages(prompt))
        raw_result = response.choices[0].message.content
        if self.verbose:
            print(f"AI 返回原始结果: {raw_result}")
        return self._clean_response(raw_result or "")

    def _prepare_text(self, content: str, title: Optional[str] = None) -> str:
        body = (content or "")[: self.max_content_chars]
        if title:
            return f"标题: {title}\n\n{body}"
        return body

    @staticmethod
    def _is_retryable_error(exc: BaseException) -> bool:
        if isinstance(
            exc,
            (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
        ):
            return True
        if isinstance(exc, APIStatusError) and exc.status_code in RETRYABLE_HTTP_STATUS:
            return True
        return False

    @staticmethod
    def _error_summary(exc: BaseException) -> str:
        if isinstance(exc, APIStatusError):
            return f"HTTP {exc.status_code}"
        return type(exc).__name__

    def _chat_completion_with_retry(self, messages: List[Dict[str, str]]):
        """带全局限速、并发上限与指数退避的 LLM 调用。"""
        last_error: Optional[BaseException] = None
        with LLM_CONCURRENCY:
            for attempt in range(self.max_retries):
                LLM_RATE_LIMITER.wait()
                try:
                    return self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.1,
                        max_tokens=256,
                        top_p=0.9,
                    )
                except Exception as e:
                    last_error = e
                    if not self._is_retryable_error(e) or attempt >= self.max_retries - 1:
                        raise
                    wait = min(2**attempt + random.uniform(0.2, 1.0), 45.0)
                    print(
                        f"⏳ LLM 暂时不可用 ({self._error_summary(e)})，"
                        f"{wait:.1f}s 后重试 ({attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(wait)
        if last_error:
            raise last_error
        raise RuntimeError("LLM request failed without exception")

    def _refine_to_leaf_path(self, parent_path: str, user_text: str) -> str:
        """Run a second pass when the first result stops at a non-leaf category."""
        if self._is_leaf_path(parent_path):
            return parent_path

        candidates = self._leaf_descendants(parent_path)
        if not candidates:
            print(f"警告: 路径 '{parent_path}' 没有可用叶子子路径，回退为 Others")
            return "Others"

        keyword_path = self._keyword_refine_leaf(parent_path, candidates, user_text)
        if keyword_path:
            if self.verbose:
                print(f"关键词下钻: '{parent_path}' -> '{keyword_path}'")
            return keyword_path

        if self.verbose:
            print(f"路径 '{parent_path}' 不是叶子，进入二次下钻分类")
        prompt = self._build_refinement_prompt(parent_path, candidates, user_text)
        raw_path = self._request_path(prompt)
        refined = self._validate_path(raw_path, candidate_paths=candidates, leaf_only=True)
        if refined in candidates:
            return refined

        print(f"警告: 无法将 '{parent_path}' 下钻到叶子路径，回退为 Others")
        return "Others"

    def classify(
        self,
        content: str,
        obj_token: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, List[str]]]:
        """主分类方法，返回 JSON 格式的标签路径；正文为空时不分类（不论标题）。"""
        if not (content or "").strip():
            return None

        if self.cache and obj_token:
            cached = self.cache.get(obj_token, content or "")
            if cached is not None:
                cached_path = self._tag_to_path(cached)
                if self._is_leaf_path(cached_path):
                    if self.verbose:
                        print(f"📦 使用分类缓存: {obj_token}")
                    return cached
                if self.verbose:
                    print(f"📦 忽略非叶子分类缓存: {obj_token} -> {cached_path}")

        truncated = self._prepare_text(content, title)
        prompt = self._build_prompt(truncated)

        try:
            raw_path = self._request_path(prompt)
            path_str = self._validate_path(raw_path)
            if not self._is_leaf_path(path_str):
                path_str = self._refine_to_leaf_path(path_str, truncated)
            result = self._path_to_json(path_str)

            if self.cache and obj_token:
                try:
                    self.cache.set(obj_token, content or "", result)
                except Exception as cache_exc:
                    print(f"警告: 分类缓存写入失败，继续返回分类结果: {cache_exc}")
            return result

        except Exception as e:
            title_hint = f" ({title})" if title else ""
            print(f"调用 LLM API 失败{title_hint}: {e}")
            return None
    
    def get_all_labels(self) -> List[str]:
        """获取所有根标签"""
        return self.root_labels
    
    def get_paths_by_keyword(self, keyword: str) -> List[str]:
        """根据关键词查找可能的路径"""
        keyword_lower = keyword.lower()
        matches = []
        for path in self.valid_paths:
            if keyword_lower in path.lower():
                matches.append(path)
        return matches
    
    def print_tree(self):
        """打印完整的标签树（用于调试）"""
        print("="*60)
        print("完整标签树结构")
        print("="*60)
        print(self.tree_description)
        print(f"\n总计: {len(self.valid_paths)} 条路径")
        print(f"根标签: {self.root_labels}")

