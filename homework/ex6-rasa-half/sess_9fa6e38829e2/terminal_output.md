homework-pub-booking % make ex6-real


✓ Rasa is up at http://localhost:5005
    HTTP 200 — {"version":"3.16.4","minimum_compatible_version":"3.16.0rc2"}
✓ Action server is up at http://localhost:5055
    HTTP 200 — {"status":"ok"}

▶ Running Ex6 scenario...

📂 Session sess_9fa6e38829e2
   dir: /Users/sotiris/Development/courses/AI performance engineering/homework-pub-booking/examples/ex6-rasa-half/sess_9fa6e38829e2
   (tier 2: assuming rasa-actions + rasa-serve are already
    running in two other terminals. If you see a connection
    error below, run `make ex6-help` for the setup recipe.)
   Rasa URL: http://localhost:5005/webhooks/rest/webhook

Structured half outcome: complete
  summary: booking confirmed by rasa (ref=BK-7D401E9E. IS THERE ANYTHING ELSE I CAN HELP YOU WITH?)
  output:  {'committed': True, 'booking': {'action': 'confirm_booking', 'venue_id': 'haymarket_tap', 'date': '2026-04-25', 'time': '19:30', 'party_size': 6, 'deposit_gbp': 200}, 'booking_reference': 'BK-7D401E9E. IS THERE ANYTHING ELSE I CAN HELP YOU WITH?', 'rasa_response': [{'recipient_id': 'homework_agent', 'text': 'Booking confirmed. Reference: BK-7D401E9E.'}, {'recipient_id': 'homework_agent', 'text': 'Is there anything else I can help you with?'}]}

📂 Session artifacts: /Users/sotiris/Development/courses/AI performance engineering/homework-pub-booking/examples/ex6-rasa-half/sess_9fa6e38829e2
📜 Narrate this run:   make narrate SESSION=sess_9fa6e38829e2