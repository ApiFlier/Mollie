import re

path = '/mollie/index.html'
with open(path, 'r') as f:
    html = f.read()

button_html = '<a href="/admin/" style="position: absolute; top: 15px; right: 15px; background: #ffffff; color: #333333; padding: 6px 14px; text-decoration: none; border-radius: 20px; font-size: 13px; font-weight: 600; z-index: 9999; box-shadow: 0 2px 6px rgba(0,0,0,0.2); border: 1px solid #e0e0e0; font-family: sans-serif; transition: background 0.2s;">Admin Panel</a>'

if 'href="/admin/"' not in html:
    # Safely insert right after the opening body tag
    html = re.sub(r'(<body[^>]*>)', r'\1\n  ' + button_html, html, 1)
    
    # Bump the version tag to break cache
    html = re.sub(r'(filters\.js\?v=)[^"]*', r'\g<1>20260428d', html)
    
    with open(path, 'w') as f:
        f.write(html)
    print("Admin button added and cache bumped!")
else:
    print("Admin button already exists.")
