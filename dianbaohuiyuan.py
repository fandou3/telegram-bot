import os
import json
import time
import base64
import aiohttp
import asyncio
import logging
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.utils import Address, to_nano, bytes_to_b64str
from tonsdk.boc import Cell, begin_cell
from tonsdk.provider import ToncenterClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 公共变量
USER_NAME = os.getenv("OpenUserName", "xiaoemo999")  # 需要开通的用户名
DURATION = int(os.getenv("OpenDuration", "3"))   # 需要开通的月份
HASH = os.getenv("ResHash")            # 接口的hash
COOKIE = os.getenv("ResCookie")        # 接口的 cookie
API_URL = f"https://fragment.com/api?hash={HASH}"  # 修改API URL格式
MNEMONIC = os.getenv("WalletMnemonic")  # 钱包助记词

class PaymentService:
    def __init__(self):
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """发送请求到Fragment API"""
        data = {}
        for key in ["query", "months", "recipient", "id", "show_sender", "mode", "lv", "dh", "transaction"]:
            if key in payload and payload[key] is not None:
                data[key] = str(payload[key]) if isinstance(payload[key], (int, bool)) else payload[key]

        data["method"] = payload["method"]

        headers = {
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "zh-CN,zh;q=0.9",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": COOKIE,
            "origin": "https://fragment.com",
            "priority": "u=1, i",
            "referer": "https://fragment.com/premium/gift",
            "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest"
        }

        try:
            logger.info(f"发送请求: {data['method']}")
            async with self.session.post(API_URL, data=data, headers=headers) as response:
                result = await response.json()
                if result.get("error"):
                    raise Exception(f"请求失败: {result['error']}")
                return result
        except Exception as e:
            logger.error(f"请求异常: {str(e)}")
            raise

    async def get_raw_request(self, id: str) -> Tuple[str, str]:
        """获取原始请求数据"""
        confirm_order_result = await self.send_request({
            "id": id,
            "show_sender": 1,
            "transaction": "1",
            "method": "getGiftPremiumLink"
        })

        if not confirm_order_result.get("transaction"):
            raise Exception("未获取到交易信息")

        transaction = confirm_order_result["transaction"]
        message = transaction["messages"][0]
        amount = message.get("amount")
        if not amount:
            raise Exception("未获取到交易金额")
        pay_amount = f"{amount/1e9}"

        logger.info(f"原始数据：{confirm_order_result.get('transaction').get('messages')[0]['payload']}")

        payload = confirm_order_result.get("transaction").get("messages")[0]['payload']
        # payload = "te6ccgEBAgEANgABTgAAAABUZWxlZ3JhbSBQcmVtaXVtIGZvciAzIG1vbnRocyAKClJlZgEAFCN3WWRWS3AwbTE"

        # 自动补充Base64填充
        def correct_padding(s):
            return s + '=' * ((4 - len(s) % 4) % 4)

            # 修复填充后解码

        decoded_bytes = base64.b64decode(correct_padding(payload))

        # 转换为字符串并忽略解码错误
        decoded_str = decoded_bytes.decode('utf-8', errors='ignore')

        # 提取目标字符串
        ref_index = decoded_str.find('#')
        if ref_index != -1:
            ref = decoded_str[ref_index + 1:].split()[0]  # 提取到第一个空格/换行处
            return ref, pay_amount
        else:
            return None, None


    @staticmethod
    def extract_ref_from_binary(data: bytes) -> str:
        """从二进制数据中提取引用ID"""
        ref_str = ""
        hash_pos = data.find(b'#')
        if hash_pos != -1:
            hash_pos += 1
            while hash_pos < len(data) and len(ref_str) < 8:
                if chr(data[hash_pos]).isalnum():
                    ref_str += chr(data[hash_pos])
                hash_pos += 1
        return ref_str

async def transfer_ton(amount: str, payload: str):
    """执行TON转账"""
    logger.info("\n=== 开始转账流程 ===")
    logger.info(f"转账金额: {amount} TON")
    logger.info(f"转账数据: {payload}")

    try:
        # 初始化TON客户端
        client = ToncenterClient(
            base_url='https://ton-mainnet.core.chainstack.com',
            api_key='f2a2411bce1e54a2658f2710cd7969c3'
        )

        # 创建钱包实例
        mnemonics, pub_k, priv_k, wallet = Wallets.from_mnemonics(
            MNEMONIC.split(),
            WalletVersionEnum.v4r2,
            workchain=0
        )

        # 获取钱包地址
        wallet_address = wallet.address.to_string(True, True, False)
        logger.info(f"钱包地址: {wallet_address}")

        logger.info(client.raw_get_account_state(wallet_address))

        # 获取当前余额
        try:
            # 直接使用aiohttp发送请求
            async with aiohttp.ClientSession() as session:
                # 获取余额
                balance_url = f"{client.base_url}/f2a2411bce1e54a2658f2710cd7969c3/api/v2/getAddressInformation"
                params = {
                    "address": wallet_address
                }
                headers = {
                    "accept": "application/json"
                }
                async with session.get(balance_url, params=params, headers=headers) as response:
                    balance_response = await response.json()
                    logger.info(f"余额响应: {balance_response}")
                    
                    if not balance_response.get('ok'):
                        raise Exception("获取余额请求失败")
                        
                    if 'result' not in balance_response or 'balance' not in balance_response['result']:
                        raise Exception("响应中没有找到余额信息")
                    
                    balance = int(balance_response['result']['balance'])
                    balance_ton = balance / 1e9
                    logger.info(f"当前余额: {balance_ton} TON")

                    if balance_ton < float(amount):
                        raise Exception(f"余额不足: {balance_ton} TON < {amount} TON")

                # 获取序列号
                seqno_url = f"{client.base_url}/f2a2411bce1e54a2658f2710cd7969c3/api/v2/runGetMethod"
                seqno_data = {
                    "address": wallet_address,
                    "method": "seqno",
                    "stack": []
                }
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json"
                }
                async with session.post(seqno_url, json=seqno_data, headers=headers) as response:
                    seqno_response = await response.json()
                    logger.info(f"序列号响应: {seqno_response}")

                    # 解析序列号
                    stack = seqno_response['result']['stack']
                    if not stack:
                        seqno = 0
                    else:
                        first_item = stack[0]  # 获取第一个元素
                        if isinstance(first_item, list) and len(first_item) == 2:
                            hex_value = first_item[1]  # 获取第二个元素，即 '0x1'
                            seqno = int(hex_value.replace('0x', ''), 16)  # 转换为十进制
                        else:
                            seqno = 0
                    logger.info(f"序列号: {seqno}")

        except Exception as e:
            raise Exception(f"获取钱包余额失败: {str(e)}")

        # 创建转账消息
        comment = f"Telegram Premium for {DURATION} months \n\nRef#{payload}"
        message = begin_cell()\
            .store_uint(0, 32)\
            .store_string(comment)\
            .end_cell()

        # 目标地址
        to_address = Address("EQBAjaOyi2wGWlk-EDkSabqqnF-MrrwMadnwqrurKpkla9nE")
        logger.info(f"目标地址: {to_address.to_string()}")

        # 创建转账交易
        transfer = wallet.create_transfer_message(
            to_addr=to_address,
            amount=to_nano(float(amount), 'ton'),
            payload=message,
            seqno=seqno,
            send_mode=3
        )

        # 确保消息的bounce标志为False
        if hasattr(transfer['message'], 'bounce'):
            transfer['message'].bounce = False
        else:
            # 如果无法直接设置bounce，重新创建消息
            new_message = begin_cell()\
                .store_uint(0, 32)\
                .store_string(comment)\
                .end_cell()
            new_message.bounce = False
            
            transfer = wallet.create_transfer_message(
                to_addr=to_address,
                amount=to_nano(float(amount), 'ton'),
                payload=new_message,
                seqno=seqno,
                send_mode=3
            )

        # 发送交易
        boc = transfer['message'].to_boc(False)
        boc_base64 = base64.b64encode(boc).decode('utf-8')

        # 添加重试机制
        max_retries = 3
        retry_delay = 2

        send_boc_url = f"https://ton-mainnet.core.chainstack.com/f2a2411bce1e54a2658f2710cd7969c3/api/v2/sendBoc"
        headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }
        payload = {"boc": boc_base64}

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(send_boc_url, json=payload, headers=headers) as response:
                        send_response = await response.json()
                        logger.info(f"发送交易响应: {send_response}")
                        if not send_response.get('ok'):
                            error_msg = send_response.get('error', '未知错误')
                            if 'rate limit' in str(error_msg).lower():
                                if attempt < max_retries - 1:
                                    logger.warning(f"遇到速率限制，等待 {retry_delay} 秒后重试...")
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2  # 指数退避
                                    continue
                            raise Exception(f"发送交易失败: {error_msg}")
                        
                        # 获取交易哈希
                        tx_hash = send_response.get('result', {}).get('hash', '')
                        if not tx_hash:
                            # 如果没有直接返回hash，尝试从extra中获取
                            extra = send_response.get('result', {}).get('@extra', '')
                            if extra:
                                tx_hash = extra.split(':')[0]  # 获取时间戳作为临时标识
                            else:
                                tx_hash = 'unknown'
                                
                        logger.info(f"交易发送成功! 交易hash: {tx_hash}")
                        logger.info(f"查看交易: https://tonscan.org/tx/{tx_hash}")
                        break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise Exception(f"发送交易失败，已重试 {max_retries} 次: {str(e)}")
                logger.warning(f"发送交易失败，{retry_delay} 秒后重试: {str(e)}")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # 指数退避

    except Exception as e:
        logger.error(f"转账失败: {str(e)}")
        raise

async def main():
    """主函数"""
    load_dotenv()
    
    if not all([USER_NAME, DURATION, HASH, COOKIE, MNEMONIC]):
        logger.error("错误: 请检查环境变量是否完整设置")
        return
    
    async with PaymentService() as ps:
        try:
            # 第一步：获取对方信息
            logger.info("\n=== 第一步：获取对方信息 ===")
            result1 = await ps.send_request({
                "query": USER_NAME,
                "months": int(DURATION),
                "method": "searchPremiumGiftRecipient"
            })
            recipient = result1["found"]["recipient"]
            userName = result1["found"].get("name", "未知")
            logger.info(f"用户昵称: {userName}")
            logger.info(f"唯一标识: {recipient}")
            
            # 第二步：创建TON支付订单
            logger.info("\n=== 第二步：创建TON支付订单 ===")
            result2 = await ps.send_request({
                "recipient": recipient,
                "months": int(DURATION),
                "method": "initGiftPremiumRequest"
            })
            req_id = result2["req_id"]
            amount = result2["amount"]
            logger.info(f"订单号: {req_id}")
            logger.info(f"金额(TON): {amount}")

            # 更新Premium状态
            logger.info("\n=== 更新Premium状态 ===")
            await ps.send_request({
                "mode": "new",
                "lv": "false",
                "dh": "1761547136",
                "method": "updatePremiumState"
            })
            
            # 第三步：确认支付订单
            logger.info("\n=== 第三步：确认支付订单 ===")
            confirm_order_result = await ps.send_request({
                "id": req_id,
                "transaction": "1",
                "show_sender": 1,
                "method": "getGiftPremiumLink"
            })
            
            # 第四步：解码订单数据
            logger.info("\n=== 第四步：解码订单数据 ===")
            payload, amount = await ps.get_raw_request(req_id)
            if payload:
                logger.info(f"支付金额: {amount} TON")
                logger.info(f"订单数据: Telegram Premium for {DURATION} months \n\nRef#{payload}")

                # 第五步：执行转账
                logger.info("\n=== 第五步：执行转账 ===")
                await transfer_ton(amount, payload)
            else:
                logger.info('异常失败')
            
        except Exception as e:
            logger.error(f"错误: {str(e)}")
            raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序执行失败: {str(e)}")
