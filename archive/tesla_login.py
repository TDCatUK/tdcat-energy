import teslapy

# Replace this with your actual Tesla Account email
EMAIL = "torsten@tdcat.com" 

with teslapy.Tesla(EMAIL) as tesla:
    if not tesla.authorized:
        print("Initiating Tesla Login...")
        tesla.fetch_token()
        print("Success! Your secure token has been cached for OTTO.")
    else:
        print("OTTO is already authorized!")
