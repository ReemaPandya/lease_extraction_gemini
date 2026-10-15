
import os
from mistralai.client import Mistral

client = Mistral(
    api_key=os.environ["MISTRAL_API_KEY"]
)

response = client.chat.complete(
    # model="mistral-small-2603",
    model="ministral-8b-2512",
    messages=[
        {
            "role": "user",
            "content": "Reply with exactly: Mistral API working"
        }
    ],
    temperature=0,
    max_tokens=30,
)

print(response.choices[0].message.content)
