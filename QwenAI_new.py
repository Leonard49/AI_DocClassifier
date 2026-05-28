#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 Qwen API 的多层级标签树文本分类器
输出 JSON 格式，例如 {"tag1": ["Cellular"], "tag2": ["4G network"]}
"""

import os
import json
import random
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


class QwenTreeClassifier:
    """使用 Qwen API 对文本进行多层级标签树分类，输出 JSON 格式的路径"""

    # 固定配置
    QWEN_API_KEY = "sk-9neu2wGxtXiOb9EcBDlL6g"
    QWEN_BASE_URL = "https://qlitellm.phicotek.com/v1"
    QWEN_MODEL = "qwen3.6-plus"

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
    ):
        self.api_key = api_key or self.QWEN_API_KEY
        if self.api_key == "your_qwen_api_key_here":
            raise ValueError("请设置有效的 Qwen API Key")
        self.model = self.QWEN_MODEL
        self.base_url = self.QWEN_BASE_URL
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

        # 预计算所有合法路径（用于后校验）
        self.valid_paths = self._extract_all_paths(self.LABEL_TREE)
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

你的任务：从下面给定的标签树中，选择**唯一一条最合理的层级路径**。

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

3. 不允许"跳级"或"并列误用"
   - 如果选了子类，必须包含它的父类
   - 例如："5G Network" -> "Cellular -> 5G Network"

4. 只能输出一条路径（最匹配的一条）

5. 输出必须完全匹配树中的名称（大小写敏感）

6. 如果无法匹配，输出：Others

====================
【输出格式（严格）】

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

    def _validate_path(self, path_str: str) -> str:
        """验证路径是否有效，无效则尝试修正或返回 Others"""
        if path_str == "Others":
            return path_str
        
        # 直接匹配
        if path_str in self.valid_paths:
            return path_str
        
        # 尝试模糊匹配
        for valid in self.valid_paths:
            if path_str in valid or valid in path_str:
                print(f"模糊匹配: '{path_str}' -> '{valid}'")
                return valid
        
        # 尝试部分匹配（只匹配最后一级）
        last_part = path_str.split(" -> ")[-1]
        for valid in self.valid_paths:
            if valid.endswith(f" -> {last_part}") or valid == last_part:
                print(f"部分匹配: '{path_str}' -> '{valid}'")
                return valid
        
        print(f"警告: 路径 '{path_str}' 不在预定义标签树中，回退为 Others")
        return "Others"

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

    def classify(
        self,
        content: str,
        obj_token: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """主分类方法，返回 JSON 格式的标签路径"""
        if not (content or "").strip() and not title:
            return {"tag1": ["Others"]}

        if self.cache and obj_token:
            cached = self.cache.get(obj_token, content or "")
            if cached is not None:
                if self.verbose:
                    print(f"📦 使用分类缓存: {obj_token}")
                return cached

        truncated = self._prepare_text(content, title)
        prompt = self._build_prompt(truncated)

        messages = [
            {
                "role": "system",
                "content": "你是一个专业的技术文档分类专家。严格按照分类规则输出，不添加任何额外内容。",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            response = self._chat_completion_with_retry(messages)
            raw_result = response.choices[0].message.content
            if self.verbose:
                print(f"AI 返回原始结果: {raw_result}")

            path_str = self._clean_response(raw_result or "")
            path_str = self._validate_path(path_str)
            result = self._path_to_json(path_str)

            if self.cache and obj_token:
                self.cache.set(obj_token, content or "", result)
            return result

        except Exception as e:
            title_hint = f" ({title})" if title else ""
            print(f"调用 Qwen API 失败{title_hint}: {e}")
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

