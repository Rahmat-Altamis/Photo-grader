
def best_use(grades: dict, min_score: int = 4) -> str:
    scores = {"1": grades["post"], "2": grades["sell"], "3": grades["compete"]}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= min_score else "0"

def base_name(use: str, grades: dict) -> str:
    return f"{use}-{grades['theme']}-{grades['edit']}"
 
