package cn.shuxin.car.mcp

import cn.shuxin.car.motor.MotorLink
import cn.shuxin.car.motor.WheelMap
import org.json.JSONArray
import org.json.JSONObject

class McpHandler(
    private val motor: MotorLink,
    private val sendJson: (JSONObject) -> Unit,
    private val onMotorUi: (String) -> Unit,
    private val onScreenCall: (String, JSONObject) -> Boolean = { _, _ -> false },
) {
    fun handle(message: JSONObject) {
        val payload = message.optJSONObject("payload") ?: return
        if (!payload.has("method") || payload.isNull("id")) return
        val id = payload.get("id")
        when (payload.optString("method")) {
            "initialize" -> sendResult(id, initializeResult())
            "tools/list" -> sendResult(id, toolsListResult())
            "tools/call" -> handleCall(id, payload.optJSONObject("params"))
        }
    }

    private fun handleCall(id: Any, params: JSONObject?) {
        val name = params?.optString("name").orEmpty()
        val args = params?.optJSONObject("arguments") ?: JSONObject()
        val handled = when {
            name in CHASSIS_TOOLS -> {
                handleChassis(name, args)
                true
            }
            else -> onScreenCall(name, args)
        }
        sendResult(
            id,
            JSONObject()
                .put(
                    "content",
                    JSONArray().put(
                        JSONObject().put("type", "text").put("text", if (handled) "true" else "unsupported"),
                    ),
                )
                .put("isError", !handled),
        )
    }

    private fun handleChassis(name: String, args: JSONObject) {
        val durationMs = ((args.optDouble("duration", args.optDouble("seconds", 1.5))) * 1000.0)
            .toInt()
            .coerceIn(0, 4000)
        val speed = args.optDouble("speed", 0.55)
        if (name.endsWith("stop")) {
            motor.emergencyStop()
        } else {
            val (left, right) = WheelMap.wheelsFor(name, speed)
            motor.setMotor(left, right, durationMs)
        }
    }

    private fun sendResult(id: Any, result: JSONObject) {
        sendJson(
            JSONObject()
                .put("type", "mcp")
                .put(
                    "payload",
                    JSONObject()
                        .put("jsonrpc", "2.0")
                        .put("id", id)
                        .put("result", result),
                ),
        )
    }

    private fun initializeResult(): JSONObject {
        return JSONObject()
            .put("protocolVersion", "2024-11-05")
            .put("capabilities", JSONObject().put("tools", JSONObject()))
            .put(
                "serverInfo",
                JSONObject().put("name", "shuxin-android").put("version", "0.1.0"),
            )
    }

    private fun toolsListResult(): JSONObject {
        val tools = JSONArray()
        CHASSIS_TOOLS.forEach { name ->
            val properties = JSONObject()
            if (name != "self.chassis.stop") {
                properties.put("duration", JSONObject().put("type", "number"))
                properties.put("speed", JSONObject().put("type", "number"))
            }
            tools.put(tool(name, "底盘：$name", properties))
        }
        tools.put(
            tool(
                "self.clock.set_timer",
                "开始倒计时。用户说几分钟以后叫我、定个闹钟、倒计时时调用。",
                JSONObject()
                    .put("seconds", JSONObject().put("type", "number"))
                    .put("minutes", JSONObject().put("type", "number")),
            ),
        )
        tools.put(
            tool(
                "self.display.weather",
                "在屏幕上展示天气。查完天气后把城市、温度和概况填进来。",
                JSONObject()
                    .put("region", JSONObject().put("type", "string"))
                    .put("temperature", JSONObject().put("type", "number"))
                    .put("summary", JSONObject().put("type", "string")),
            ),
        )
        tools.put(
            tool(
                "self.camera.look",
                "看眼前这一眼。用户说这是什么、前面有什么、摄像头、看看这时调用。环顾四周请用 look_around。",
                JSONObject(),
            ),
        )
        tools.put(
            tool(
                "self.camera.look_around",
                "转头环顾四周再看环境。用户问看到了什么、看见什么、环顾、看看周围时调用。",
                JSONObject(),
            ),
        )
        tools.put(
            tool(
                "self.camera.photo",
                "拍一张照片存进相册。用户说拍照、拍一张时调用。",
                JSONObject(),
            ),
        )
        tools.put(
            tool(
                "self.camera.album",
                "打开相册看拍过的照片。用户说相册、看看照片时调用。",
                JSONObject(),
            ),
        )
        tools.put(
            tool(
                "self.head.nod",
                "头部点头。用户说点头、点点头时调用。",
                JSONObject(),
            ),
        )
        tools.put(
            tool(
                "self.head.shake",
                "头部摇头。用户说摇头、摇摇头时调用。",
                JSONObject(),
            ),
        )
        tools.put(
            tool(
                "self.head.turn",
                "把头转到指定角度。pan 左右 0-180（90 正前），tilt 上下 0-180（90 水平）。",
                JSONObject()
                    .put("pan", JSONObject().put("type", "number"))
                    .put("tilt", JSONObject().put("type", "number")),
            ),
        )
        return JSONObject().put("tools", tools)
    }

    private fun tool(name: String, description: String, properties: JSONObject): JSONObject {
        return JSONObject()
            .put("name", name)
            .put("description", description)
            .put(
                "inputSchema",
                JSONObject()
                    .put("type", "object")
                    .put("properties", properties),
            )
    }

    companion object {
        val CHASSIS_TOOLS = listOf(
            "self.chassis.go_forward",
            "self.chassis.go_back",
            "self.chassis.turn_left",
            "self.chassis.turn_right",
            "self.chassis.stop",
        )
    }
}
