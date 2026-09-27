import json
from pathlib import Path
from bot import compose

BASE = Path(__file__).parent.parent / "magicpin" / "expanded"


def load(kind, cid):
    return json.load(open(BASE / kind / f"{cid}.json"))


def main():
    test_pairs = json.load(open(BASE / "test_pairs.json"))["pairs"]
    out = []
    for pair in test_pairs:
        trigger = load("triggers", pair["trigger_id"])
        merchant = load("merchants", pair["merchant_id"])
        category = load("categories", merchant["category_slug"])
        customer = load("customers", pair["customer_id"]) if pair.get("customer_id") else None
        result = compose(category, merchant, trigger, customer)
        out.append({
            "test_id": pair["test_id"],
            "body": result["body"],
            "cta": result["cta"],
            "send_as": result["send_as"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"],
        })
    with open(Path(__file__).parent / "submission.jsonl", "w") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    for row in out:
        print(row["test_id"], "|", row["body"][:140])


if __name__ == "__main__":
    main()
