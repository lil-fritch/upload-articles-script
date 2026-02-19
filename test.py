import requests
import json
import time

# Конфігурація
BASE_URL = "http://exo.renew.wtf"
url = f"{BASE_URL}/v1/chat/completions?async=true"
api_key = "p8rTCFOWUfjuAO5q4ZswLvW4H1nh4vfjeAIhCKb9OUc"

POLL_INTERVAL = 1  # секунди між запитами
MAX_WAIT = 120*5  # максимальний час очікування

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
    # Крок 1: Відправляємо запит і отримуємо task_id
    print("Відправляємо запит...")
    response = requests.post(url, headers=headers, data=json.dumps(data))
    response.raise_for_status()

    result = response.json()
    print("Початкова відповідь:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Перевіряємо чи не прийшла відповідь одразу (синхронний режим)
    if "choices" in result:
        print("\n=== Синхронна відповідь ===")
        content = result["choices"][0]["message"]["content"]
        print(content)
        exit(0)

    task_id = result.get("task_id") or result.get("id")
    if not task_id:
        print("Помилка: не отримано task_id")
        exit(1)

    # Крок 2: Поллінг для отримання результату
    task_url = f"{BASE_URL}/v1/tasks/{task_id}"
    print(f"\n=== Поллінг задачі: {task_id} ===")

    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        if elapsed > MAX_WAIT:
            print(f"\nЧас очікування вичерпано ({MAX_WAIT}s)")
            break

        time.sleep(POLL_INTERVAL)
        task_response = requests.get(task_url, headers=headers)
        task_response.raise_for_status()
        task_result = task_response.json()

        status = task_result.get("status")
        print(f"Статус: {status} | Час: {elapsed:.1f}s")

        if status in ("completed", "succeeded"):
            print("\n=== Кінцевий результат ===")
            # Спробуємо різні формати відповіді
            choices = task_result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                print(content)
            else:
                print(json.dumps(task_result, indent=2, ensure_ascii=False))
            break
        elif status in ("failed", "error"):
            print("\n=== Помилка виконання ===")
            print(json.dumps(task_result, indent=2, ensure_ascii=False))
            break

except requests.exceptions.RequestException as e:
    print(f"Сталася помилка: {e}")