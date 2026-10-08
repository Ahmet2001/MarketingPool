import json
import os
from datetime import datetime

# Simulate notification data based on mock accounts
mock_notifications = {
    "twitter": [
        {"id": 1, "type": "like", "count": 5},
        {"id": 2, "type": "retweet", "count": 12}, # Important
        {"id": 3, "type": "comment", "count": 8},
        {"id": 4, "type": "like", "count": 25}  # Important
    ],
    "instagram": [
        {"id": 101, "type": "like", "count": 3},
        {"id": 102, "type": "comment", "count": 15}, # Important
        {"id": 103, "type": "dm", "count": 2}
    ]
}

threshold = 10
important_interactions = {}

for platform, notifications in mock_notifications.items():
    important_interactions[platform] = []
    for notif in notifications:
        if notif['count'] >= threshold:
            important_interactions[platform].append(notif)

# Generate Report
report_path = f"workspace/reports/social_media_report_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.md"
report_content = "# Sosyal Medya İzleme Raporu (Otomatik Görev)\n\n"
report_content += f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
report_content += "## Önemli Etkileşimler (Eşik: >=10)\n\n" # Fixed f-string usage here for clarity

found_important = False
for platform, interactions in important_interactions.items():
    if interactions:
        found_important = True
        report_content += f"### {platform.capitalize()}\n"
        for inter in interactions:
            report_content += f"- Tür: {inter['type']}, Sayı: {inter['count']} (ID: {inter['id']})\n"

if not found_important:
    report_content += "Belirlenen eşiğin üzerinde önemli bir etkileşim bulunamadı.\n"

# Save report
os.makedirs("workspace/reports", exist_ok=True)
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report_content)

print(f"Rapor başarıyla oluşturuldu: {report_path}")
print(report_content)
