import sys
import requests


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    base_url = base_url.rstrip("/")

    checks = [
        ("Health endpoint", "GET", f"{base_url}/health"),
        ("Pending operations endpoint", "GET", f"{base_url}/ops/pending"),
    ]

    failed = False

    for name, method, url in checks:
        try:
            response = requests.request(method, url, timeout=10)
            response.raise_for_status()

            if name == "Health endpoint":
                passed = response.json().get("status") == "ok"
            else:
                passed = isinstance(response.json(), list)

            print(f"{'PASS' if passed else 'FAIL'}: {name}")
            if not passed:
                failed = True

        except Exception as exc:
            print(f"FAIL: {name} - {exc}")
            failed = True

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()