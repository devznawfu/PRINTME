from printme import create_app

app = create_app("prod")

if __name__ == "__main__":
    from waitress import serve

    # 0.0.0.0, not 127.0.0.1: customer phones need to reach this over
    # the shop's LAN, not just the admin PC itself.
    serve(app, host="0.0.0.0", port=5000)
