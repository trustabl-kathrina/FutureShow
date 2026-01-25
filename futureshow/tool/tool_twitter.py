import http.client
import urllib.parse
import json
from tqdm import tqdm
import os
from agents import function_tool
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

@function_tool
def search_tweets(query, count=20):
    """搜索推文并返回结果"""
    conn = http.client.HTTPSConnection("twitter241.p.rapidapi.com")
    headers = {
        'x-rapidapi-key': RAPIDAPI_KEY,
        'x-rapidapi-host': "twitter241.p.rapidapi.com"
    }
    encoded_query = urllib.parse.quote(query)
    url = f"/search-v2?type=Top&count={count}&query={encoded_query}"
    conn.request("GET", url, headers=headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    conn.close()
    # print(data)
    len_tweets = len(data['result']['timeline']['instructions'][0]['entries'])
    tweets = {}
    for i in range(len_tweets):
        tweet_data = data['result']['timeline']['instructions'][0]['entries'][i]
        entry_id = tweet_data['entryId']
        if 'tweet' in entry_id:
            # tweet content
            tweets_content = tweet_data['content']['itemContent']['tweet_results']['result']['legacy']['full_text']
            tweets_favorite_count = tweet_data['content']['itemContent']['tweet_results']['result']['legacy']['favorite_count']
            tweets_quote_count = tweet_data['content']['itemContent']['tweet_results']['result']['legacy']['quote_count']
            tweets_reply_count = tweet_data['content']['itemContent']['tweet_results']['result']['legacy']['reply_count']
            tweets_retweet_count = tweet_data['content']['itemContent']['tweet_results']['result']['legacy']['retweet_count']
            # tweet user
            tweets_user_name = tweet_data['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['core']['name']
            tweets_user_description = tweet_data['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['description']
            tweets_user_favourites_count = tweet_data['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['favourites_count']
            tweets_user_followers_count = tweet_data['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['followers_count']
            tweets_user_friends_count = tweet_data['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['friends_count']
            tweets[entry_id] = {
                'content': tweets_content,
                'favorite_count': tweets_favorite_count,
                'quote_count': tweets_quote_count,
                'reply_count': tweets_reply_count,
                'retweet_count': tweets_retweet_count,
                'user_name': tweets_user_name,
                'user_description': tweets_user_description,
                'user_favourites_count': tweets_user_favourites_count,
                'user_followers_count': tweets_user_followers_count,
                'user_friends_count': tweets_user_friends_count,
            }
        elif 'stories' in entry_id:
            story_name = tweet_data['content']['items'][0]['item']['itemContent']['name']
            story_trend_domain_context = tweet_data['content']['items'][0]['item']['itemContent']['trend_metadata']['domain_context']
            story_trend_meta_description = tweet_data['content']['items'][0]['item']['itemContent']['trend_metadata']['meta_description']
            tweets[entry_id] = {
                'name': story_name,
                'trend_domain_context': story_trend_domain_context,
                'trend_meta_description': story_trend_meta_description,
            }
    return tweets
# 使用
if __name__ == "__main__":
    from agents.tool_context import ToolContext
    import asyncio
    ctx = ToolContext(
        context=None,
        tool_name="search_tweets",
        tool_call_id="search-tweets-test",
        tool_arguments='{"query":"spacex", "count":10}'
    )
    result = asyncio.run(
        search_tweets.on_invoke_tool(ctx, '{"query":"spacex", "count":10}')
    )
    print(result)