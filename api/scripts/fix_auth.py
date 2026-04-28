import os
path = '/mollie/api/app.py'
with open(path, 'r') as f:
    code = f.read()

if '"/auth/check"' not in code:
    code = code.replace('@app.route("/auth-check")', '@app.route("/auth-check")\n@app.route("/auth/check")')
    with open(path, 'w') as f:
        f.write(code)
        print("Backend route patched successfully!")
