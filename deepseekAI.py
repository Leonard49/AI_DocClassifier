#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 DeepSeek API 的多层级标签树文本分类器
输出 JSON 格式，例如 {"tag1": ["Cellular"], "tag2": ["4G network"]}
"""

import os
import json
from typing import Dict, List, Union, Optional, Tuple
from openai import OpenAI


class DeepSeekTreeClassifier:
    """使用 DeepSeek API 对文本进行多层级标签树分类，输出 JSON 格式的路径"""

    # 固定配置（请将 API Key 替换为你自己的真实 Key）
#    DEEPSEEK_API_KEY = "sk-88e00b5638c542c5a2ea84d64bb1fc24"   # 替换为实际 API Key
    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    DEEPSEEK_MODEL = "deepseek-v4-flash"

    # 预定义标签树（完整版，与之前相同，省略篇幅）
    LABEL_TREE = {
        "Cellular": [
            "log工具", "4G network", "5G Network", "redcap", "Starlink D2C",
            "SIM CARD", "voice call", "sms", "数据协议", "audio",
            "低功耗", "dfota", "gnss", "wifi bt", "认证", "竞品分析",
            "行业分析", "BB", "RF", "Antenna", "EMC"
        ],
        "Automotive": ["BB", "RF", "Antenna", "EMC"],
        "Smart": {
            "HW": {"EVB": [], "Logic Analyzer": [], "Oscilloscope": []},
            "BSP": {
                "LCD/TP": [], "Camera": [], "Sensor": [],
                "Gpio": [], "Audio": [], "I2C/UART/SPI/CAN": [],
                "USB": [], "SD CARD/SIM": [],
                "Fuel guage/Charging/NTC": [], "ETH/NFC/WiFi": []
            },
            "AI": {"高通 SNPE": [], "瑞芯微 RKNN": []},
            "System": {
                "OTA": [], "Thermal": [], "SELinux": [],
                "Secureboot": [], "系统优化": []
            },
            "Yocto": {
                "yocto APP开发": [], "yocto 应用内置": [], "yocto 第三方工具集成": [],
                "yocto 系统自启动": [], "yocto 系统优化&裁剪": []
            }
        },
        "ShortRange": [
            "MCU WIFI", "RF WIFI", "Bluetooth", "Matter", "Lora",
            "Zigbee", "Wisun", "M-Bus", "Halow", "UWB",
            "抓log", "Log分析", "射频测试", "认证", "打流速率", "硬件原理"
        ],
        "GNSS": {
            "GNSS功能原理": {
                "RTK": [], "PPP": [], "DR": []
            }
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
            }
        },
        "Satellite": {"IoT NTN", "NR NTN", "Startlink"},
        "Antenna": {},
        "Services": {},
        "Others": {}
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or self.DEEPSEEK_API_KEY
        if self.api_key == "your_deepseek_api_key_here":
            raise ValueError("请设置有效的 DeepSeek API Key")
        self.model = self.DEEPSEEK_MODEL
        self.base_url = self.DEEPSEEK_BASE_URL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        # 预计算所有合法路径（用于后校验）
        self.valid_paths = self._extract_all_paths(self.LABEL_TREE)
        self.root_labels = list(self.LABEL_TREE.keys())

    def _extract_all_paths(self, tree: Union[Dict, List], prefix: str = "") -> List[str]:
        paths = []
        if isinstance(tree, dict):
            for key, value in tree.items():
                current = f"{prefix} -> {key}" if prefix else key
                paths.append(current)
                if isinstance(value, dict):
                    paths.extend(self._extract_all_paths(value, current))
                elif isinstance(value, list):
                    for item in value:
                        paths.append(f"{current} -> {item}")
        elif isinstance(tree, list):
            for item in tree:
                paths.append(f"{prefix} -> {item}" if prefix else item)
        return paths

    def _build_prompt(self, user_text: str) -> str:
        tree_desc = self._format_tree_description()
        return f"""你是一个严格遵守“层级标签树”的技术分类专家。

        你的任务：从下面给定的标签树中，选择**唯一一条最合理的层级路径**。

        ====================
        【标签树（必须严格遵守）】
        - Cellular: log工具、4G network、5G Network、redcap、Starlink D2C、SIM CARD、voice call、sms、数据协议、audio、低功耗、dfota、gnss、wifi bt、认证、竞品分析、行业分析、BB、RF、Antenna、EMC
        - Automotive: BB、RF、Antenna、EMC
        - Smart:
        - HW: EVB、Logic Analyzer、Oscilloscope
        - BSP: LCD/TP、Camera、Sensor、Gpio、Audio、I2C/UART/SPI/CAN、USB、SD CARD/SIM、Fuel guage/Charging/NTC、ETH/NFC/WiFi
        - AI: 高通 SNPE、瑞芯微 RKNN
        - System: OTA、Thermal、SELinux、Secureboot、系统优化
        - Yocto: yocto APP开发、yocto 应用内置、yocto 第三方工具集成、yocto 系统自启动、yocto 系统优化&裁剪
        - ShortRange: MCU WIFI、RF WIFI、Bluetooth、Matter、Lora、Zigbee、Wisun、M-Bus、Halow、UWB、抓log、Log分析、射频测试、认证、打流速率、硬件原理
        - GNSS -> GNSS功能原理: RTK、PPP、DR
        - QuecOpen:
        - 快速入门&FAQ: SDK介绍及编译、固件升级、Log抓取、开发调试相关
        - 数据拨号: USB上网及拨号工具、PPP拨号、Open API拨号
        - 平台和系统: Dfota、Secure Boot、性能优化、GNSS、WI-FI、BlueTooth
        - Satellite、Antenna、Services、Others
         ====================

            【最重要规则（必须严格遵守）】

            1层级必须符合树结构（禁止错误层级）  
            - "4G network" 和 "5G Network" 只能属于 Cellular 的子类  
            -错误："4G network"  
            -正确："Cellular -> 4G network"

            2不允许“跳级”或“并列误用”  
            - 如果选了子类，必须包含它的父类  
            - 例如：  
            "5G Network"  
            "Cellular -> 5G Network"

            3只能输出一条路径（最匹配的一条）  

            4输出必须完全匹配树中的名称（大小写敏感）

            5如果无法匹配，输出：  
            Others

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
            {user_text}

            【分类结果】
            """
    

    def _format_tree_description(self) -> str:
        lines = [
            "- Cellular: log工具、4G Network、5G Network、redcap、Starlink D2C、SIM CARD、voice call、sms、数据协议、audio、低功耗、dfota、gnss、wifi bt、认证、竞品分析、行业分析、BB、RF、Antenna、EMC",
            "- Automotive: BB、RF、Antenna、EMC",
            "- Smart:",
            "  - HW: EVB、Logic Analyzer、Oscilloscope",
            "  - BSP: LCD/TP、Camera、Sensor、Gpio、Audio、I2C/UART/SPI/CAN、USB、SD CARD/SIM、Fuel guage/Charging/NTC、ETH/NFC/WiFi",
            "  - AI: 高通 SNPE、瑞芯微 RKNN",
            "  - System: OTA、Thermal、SELinux、Secureboot、系统优化",
            "  - Yocto: yocto APP开发、yocto 应用内置、yocto 第三方工具集成、yocto 系统自启动、yocto 系统优化&裁剪",
            "- ShortRange: MCU WIFI、RF WIFI、Bluetooth、Matter、Lora、Zigbee、Wisun、M-Bus、Halow、UWB、抓log、Log分析、射频测试、认证、打流速率、硬件原理",
            "- GNSS -> GNSS功能原理: RTK、PPP、DR",
            "- QuecOpen:",
            "  - 快速入门&FAQ: SDK介绍及编译、固件升级、Log抓取、开发调试相关",
            "  - 数据拨号: USB上网及拨号工具、PPP拨号、Open API拨号",
            "  - 平台和系统: Dfota、Secure Boot、性能优化、GNSS、WI-FI、BlueTooth",
            "- Satellite、Antenna、Services、Others"
        ]
        return "\n".join(lines)

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
        if path_str == "Others":
            return {"tag1": ["Others"]}
        # 按 " -> " 分割
        parts = [p.strip() for p in path_str.split(" -> ")]
        result = {}
        for i, part in enumerate(parts, start=1):
            result[f"tag{i}"] = [part]
        return result

    def classify(self, content: str) -> Dict[str, List[str]]:
        """主分类方法，返回 JSON 格式的标签路径"""
        truncated = content[:10000]
        prompt = self._build_prompt(truncated)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的技术文档分类专家。严格按照分类规则输出，不添加任何额外内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=256,
                top_p=0.9
            )

            raw_result = response.choices[0].message.content
            print(f"AI 返回原始结果: {raw_result}")

            path_str = self._clean_response(raw_result)

            # 可选：路径合法性校验（如果不需要校验可注释）
            if path_str != "Others" and path_str not in self.valid_paths:
                # 尝试模糊匹配
                matched = False
                for valid in self.valid_paths:
                    if path_str in valid or valid in path_str:
                        path_str = valid
                        matched = True
                        break
                if not matched:
                    print(f"警告: 路径 '{path_str}' 不在预定义标签树中，回退为 Others")
                    path_str = "Others"

            return self._path_to_json(path_str)

        except Exception as e:
            print(f"调用 DeepSeek API 失败: {e}")
            return {"tag1": ["Others"]}


