from py_clob_client.client import ClobClient
from dotenv import load_dotenv
import os
load_dotenv()

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137                     # Polygon 主网
PRIVATE_KEY = os.getenv("PRIVATE_KEY")           # 持有资金的钱包私钥
FUNDER = None                      # 若用邮箱/代理钱包，这里填资金地址，否则可不填

client = ClobClient(
    HOST,
    key=PRIVATE_KEY,
    chain_id=CHAIN_ID,
    # 如果是邮箱/Magic、或浏览器代理钱包：signature_type=1 并填写 funder
    # signature_type=0 为普通 EOA（默认）
)

# 一步到位：创建或派生 API 凭据，并设置到客户端
print(client.create_or_derive_api_creds())
print("API 凭据已就绪，可直接下单、查单等")
