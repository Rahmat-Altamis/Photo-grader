from config import EDITS, THEMES
 
 
def build_prompt() -> str:
    themes = "\n".join(f'  "{k}" = {v}' for k, v in THEMES.items())
    edits = "\n".join(f'  "{k}" = {v}' for k, v in EDITS.items())

    return f"""You are a professional photo editor and curator. Evaluate the attached image three ways. Score each from 1 to 10 (be honest, 5 is average, 9-10 is rare): post: how well it would do on social media (instant impact, eye -catching, shareable) sell: commercial value for stock / prints / clients (technical quality, clean, marketable subject, no distracting logos or people who'd need a release) compete: how it would do in a photo contest (originality, technical excellence, storytelling, strong composition) then choose ONE theme letter: {themes} and ONE edit symbol, the single most valuable improvement to make next: {edits} Reply with ONLY a JSON object, no markdown, in exactly this shape: {{"post": <1-10>, "sell": <1-10>, "compete": <1-10>, "theme": "<letter>", "edit": "<symbol>",   "edit_note": "<short, specific edit advice>", "reason": "<one short sentence>"}}"""
