import os
import mysql.connector

def main():
    db_pass = os.popen("grep DB_PASSWORD /mollie/.env | cut -d '=' -f2").read().strip().strip("'").strip('"')
    conn = mysql.connector.connect(host="localhost", port=3308, database="mollies_guide", user="mollies", password=db_pass)
    cur = conn.cursor()

    regions = {
        "Great Lakes Region": ["Mercer County Grange Fair", "Cochranton Community Fair", "Venango County Fair", "Jefferson Township Fair", "Crawford County Fair", "Transfer Harvest Home Fair", "Erie County Fair at Wattsburg", "The Great Stoneboro Fair", "Spartansburg Community Fair", "Waterford Community Fair", "Jamestown Community Fair", "Albion Area Fair"],
        "Pennsylvania Wilds": ["Sykesville Ag & Youth Fair", "Wolf's Corners Fair", "Lycoming County Fair", "Jefferson County Fair", "Clarion County Fair", "Clinton County Fair", "Potter County Fair", "Clearfield County Fair", "Cameron County Fair", "Tioga County Fair", "Warren County Fair", "Elk County Fair", "McKean County Fair", "Harmony Grange Fair"],
        "Upstate Pennsylvania": ["Troy Fair", "Harford Fair", "Sullivan County Fair", "Wyoming County Fair", "Luzerne County Fair"],
        "Pocono Mountains": ["Wayne County Fair", "Carbon County Fair", "West End Fair", "Greene-Dreher-Sterling Fair"],
        "Lehigh Valley": ["Schnecksville Community Fair", "Plainfield Farmers Fair", "Blue Valley Farm Show", "Allentown Fair"],
        "Pittsburgh & Its Countryside": ["Big Butler Fair", "Jacktown Fair", "Greene County Fair", "Butler Farm Show", "Washington County Ag Fair", "Dayton Fair", "Lawrence County Fair", "Hookstown Fair", "Indiana County Fair", "Big Knob Grange Fair", "Ox Hill Community Fair", "West Alexander Fair", "Cookport Fair"],
        "Laurel Highlands": ["PA Maple Festival", "Mountain Area Fair", "Derry Township Ag Fair", "Sewickley Twp Fair", "Fayette County Fair", "Dawson Grange Fair", "Bullskin Twp Fair", "Westmoreland Fair", "Somerset County Fair", "Berlin Brothersvalley Fair"],
        "The Alleghenies": ["Bedford County Fair", "Fulton County Fair", "Morrisons Cove Dairy Show", "Mifflin County Youth Fair", "Huntingdon County Fair", "Centre County Grange Fair", "Williamsburg Community Farm Show", "Juniata County Fair", "American Legion County Fair", "Claysburg Farm Show", "Sinking Valley Fair", "Hollidaysburg Fair"],
        "Valleys of the Susquehanna": ["Montour-Delong Fair", "Schuylkill County Fair", "Union County West End Fair", "Northumberland County Fair", "McClure Bean Soup Fair", "Beaver Community Fair", "Bloomsburg Fair"],
        "Dutch Country Roads": ["Kempton Fair", "Franklin County Fair", "Mason Dixon Fair", "The Berks County Fair", "York State Fair", "Lebanon Area Fair", "Shippensburg Community Fair", "South Mountain Fair", "Kutztown Fair", "Cumberland Ag Expo", "Perry County Community Fair", "Elizabethtown Fair", "Denver Fair", "Southern Lancaster County Fair", "Oley Valley Fair", "Gratz Fair", "Ephrata Fair", "West Lampeter Fair", "New Holland Farmers Fair", "Manheim Farm Show", "Dillsburg Farmers Fair", "PA Farm Show", "Unionville Fair"],
        "Philadelphia & Its Countryside": ["Delaware Val Univ. A Day", "Kimberton Fair", "Goshen Country Fair", "Middletown Grange Fair"]
    }

    for region, fair_names in regions.items():
        for name in fair_names:
            cur.execute("UPDATE locations SET county = %s WHERE name LIKE %s AND category_id = 4", (region, f"%{name}%"))
    
    conn.commit()
    cur.close()
    conn.close()
    print("Regions successfully assigned to fairs!")

if __name__ == "__main__":
    main()
