import os
import json
import http.client

def eposta_ozetle(eposta_metni: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Hata: OPENAI_API_KEY tanımlı değil."

    try:
        conn = http.client.HTTPSConnection("api.openai.com")
        payload = json.dumps({
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "Sen profesyonel bir asistansın. Sana verilen e-postayı tek cümleyle veya madde işaretleriyle özetle."},
                {"role": "user", "content": eposta_metni}
            ],
            "temperature": 0.5
        })
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        conn.request("POST", "/v1/chat/completions", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        response_json = json.loads(data)

        if "choices" in response_json:
            return response_json["choices"][0]["message"]["content"]
        else:
            return f"Hata oluştu: {data}"
    except Exception as e:
        return f"Bir hata meydana geldi: {str(e)}"
