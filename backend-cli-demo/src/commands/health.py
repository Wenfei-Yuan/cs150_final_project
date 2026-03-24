def check_health(api_client):
    response = api_client.get_health()
    if response.status_code == 200:
        print("API is healthy!")
        print("Response:", response.json())
    else:
        print("API is not healthy!")
        print("Status Code:", response.status_code)
        print("Response:", response.text)