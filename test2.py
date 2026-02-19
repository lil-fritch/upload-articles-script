import requests
import json

# Звичайний синхронний запит (без ?async=true)
url = "http://exo.renew.wtf/v1/chat/completions"
api_key = "p8rTCFOWUfjuAO5q4ZswLvW4H1nh4vfjeAIhCKb9OUc"

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
    response.raise_for_status()

    result = response.json()
    print("Відповідь моделі:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Спробуємо дістати текст
    choices = result.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        print(f"\n=== ТЕКСТ ВІДПОВІДІ ===\n{content}")

except requests.exceptions.RequestException as e:
    print(f"Сталася помилка: {e}")
