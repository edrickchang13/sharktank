import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from getstream import Stream

    api_key = os.environ.get("STREAM_API_KEY")
    api_secret = os.environ.get("STREAM_API_SECRET")

    if not api_key or not api_secret:
        print("ERROR: STREAM_API_KEY or STREAM_API_SECRET not set in .env")
        sys.exit(1)

    print(f"API key loaded: {api_key[:4]}...{api_key[-4:]}")

    client = Stream(api_key=api_key, api_secret=api_secret)

    # Generate a server-side token for a test agent user
    token = client.create_token("test-agent-user")
    print(f"Token generated: {token[:20]}...")

    # Create/get a call via the REST API — this round-trips to Stream's servers
    # and will 401 immediately if credentials are wrong
    from getstream.models import CallRequest, UserRequest
    call = client.video.call("default", "sharktank-test-connection")
    response = call.get_or_create(
        data=CallRequest(created_by=UserRequest(id="test-agent-user"))
    )

    print(f"Call created/fetched: {response.data.call.cid}")
    print("Stream connection successful")

except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
