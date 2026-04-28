import os
path = '/mollie/api/app.py'
with open(path, 'r') as f:
    code = f.read()

new_route = """
@app.route("/locations/<int:loc_id>/notes/<int:note_id>", methods=["DELETE"])
def delete_note(loc_id, note_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE id = %s AND location_id = %s", (note_id, loc_id))
        conn.commit()
        cur.close()
        return jsonify({"ok": True})
    finally:
        conn.close()

if __name__ == "__main__":
"""

if "def delete_note" not in code:
    code = code.replace('if __name__ == "__main__":', new_route.strip() + '\n')
    with open(path, 'w') as f:
        f.write(code)
        print("Delete route successfully injected!")
