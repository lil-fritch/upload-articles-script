import requests
import json

# Конфігурація
url = "http://exo.renew.wtf/v1/chat/completions"
api_key = "p8rTCFOWUfjuAO5q4ZswLvW4H1nh4vfjeAIhCKb9OUc"  # Замініть на свій реальний ключ

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

data = {
    "model": "mlx-community/gpt-oss-20b-MXFP4-Q8",
    "messages": [
        {
            "role": "user",
            "content": "Привет! Ты кто?"
        }
    ],
    "max_tokens": 150,
    "temperature": 0.7
}

try:
    response = requests.post(url, headers=headers, data=json.dumps(data))
    response.raise_for_status()  # Перевірка на помилки HTTP
    
    result = response.json()
    print("Відповідь моделі:")
    print(result)

except requests.exceptions.RequestException as e:
    print(f"Сталася помилка: {e}")