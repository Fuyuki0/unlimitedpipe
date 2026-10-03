from unlimitedpipe.sources.faa import airport_status, minutes

SAMPLE = (
    "<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Oct 3 20:17:42 2026 GMT</Update_Time>"
    "<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>MCO</ARPT>"
    "<Reason>thunderstorms</Reason><End_Time>4:30 pm EDT</End_Time></Program>"
    "</Ground_Stop_List></Delay_type><Delay_type><Name>Ground Delay Programs</Name>"
    "<Ground_Delay_List><Ground_Delay><ARPT>SAN</ARPT><Reason>wind</Reason><Avg>49 minutes</Avg>"
    "<Max>2 hours and 18 minutes</Max></Ground_Delay></Ground_Delay_List></Delay_type>"
    "<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List>"
    '<Delay><ARPT>SEA</ARPT><Reason>RWY:Construction</Reason><Arrival_Departure Type="Departure">'
    "<Min>31 minutes</Min><Max>45 minutes</Max><Trend>Increasing</Trend></Arrival_Departure>"
    '</Delay><Delay><ARPT>BOS</ARPT><Reason>VOL:Volume</Reason><Arrival_Departure Type="Arrival">'
    "<Min>15 minutes</Min><Max>29 minutes</Max><Trend>Steady</Trend></Arrival_Departure></Delay>"
    "</Arrival_Departure_Delay_List></Delay_type></AIRPORT_STATUS_INFORMATION>"
)


def test_stops_programs_and_long_delays_read_as_sentences():
    found = airport_status(SAMPLE, min_delay=45)
    assert [f["title"] for f in found] == [
        "Ground stop at Orlando (MCO): thunderstorms, until 4:30 pm EDT",
        "Ground delays at San Diego (SAN): wind, average 49 minutes, up to 2 hours and 18 minutes",
        "Departure delays at Seattle (SEA): 31 minutes to 45 minutes, increasing "
        "(runway construction)",
    ]  # Boston's 29-minute arrival delays are left out
    assert minutes("2 hours and 18 minutes") == 138 and minutes("45 minutes") == 45
