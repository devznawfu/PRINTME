from printme import create_app

app = create_app("dev")

if __name__ == "__main__":
    # 0.0.0.0, not 127.0.0.1: customer phones need to reach this over
    # the shop's LAN, not just the admin PC itself. Still local-only -
    # this doesn't expose anything to the internet, only to whatever
    # network this machine's NIC is actually connected to.
    app.run(host="0.0.0.0", port=5000, debug=True)
