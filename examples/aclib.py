from archicad import ACConnection

conn = ACConnection.connect()

def RunTapirCommand(commandName, parameters=None):
    if parameters is None:
        parameters = {}
    print(f"Running {commandName}...")
    try:
        res = conn.commands.ExecuteAddOnCommand(
            conn.types.AddOnCommandId("TapirCommand", commandName),
            parameters
        )
        print(f"Result for {commandName}:", res)
        return res
    except Exception as e:
        print(f"Exception for {commandName}:", e)
        return {"error": str(e)}