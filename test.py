from dotenv import load_dotenv
from langchain_tavily import TavilySearch

load_dotenv(r"D:\python\agent\.env")

search = TavilySearch(
    max_results=3,
    search_depth="basic",
    include_answer=False,
    include_raw_content=False,
)

result = search.invoke({
    "query": "索尼降噪耳机 最新型号 官网"
})

for item in result.get("results", []):
    print("标题：", item["title"])
    print("链接：", item["url"])
    print("摘要：", item["content"])
    print()