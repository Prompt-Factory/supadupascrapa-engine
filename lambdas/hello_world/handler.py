import json


def handler(event, context):
    print("hello")
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "hello",
                "input": event or {},
            },
            ensure_ascii=False,
        ),
    }


if __name__ == "__main__":
    test_event = {"ping": "pong"}
    print(handler(test_event, None))
