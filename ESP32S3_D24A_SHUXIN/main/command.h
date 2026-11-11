#pragma once
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

enum class Action { Forward, Backward, Left, Right, Stop };
struct Command { Action action; int speed; };
enum class HeadKind { Set, Nod, Shake };
struct HeadCommand { HeadKind kind; int pan = 90; int tilt = 90; };
enum class EncKind { Status, Reset };
struct EncCommand { EncKind kind; };

// ENC / ENC R — 读前轮编码器计数与 cps；R 清零。
inline bool ParseEnc(char *line, EncCommand &out) {
    char *cursor = line;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    char *name = cursor;
    while (*cursor && !isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    if (*cursor) *cursor++ = '\0';
    for (char *p = name; *p; ++p) *p = static_cast<char>(toupper(static_cast<unsigned char>(*p)));
    if (strcmp(name, "ENC") && strcmp(name, "E")) return false;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    if (!*cursor) {
        out.kind = EncKind::Status;
        return true;
    }
    if ((!strcmp(cursor, "R") || !strcmp(cursor, "r") || !strcmp(cursor, "0")) && cursor[1] == '\0') {
        out.kind = EncKind::Reset;
        return true;
    }
    for (char *p = cursor; *p; ++p) *p = static_cast<char>(toupper(static_cast<unsigned char>(*p)));
    if (!strcmp(cursor, "RESET")) {
        out.kind = EncKind::Reset;
        return true;
    }
    return false;
}

// F/B/L/R [0..100] 或原语音工程同名MCP工具；停止不接受速度参数。
inline bool ParseCommand(char *line, int default_speed, Command &out) {
    char *cursor = line;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    char *name = cursor;
    while (*cursor && !isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    if (*cursor) *cursor++ = '\0';
    if (!strcmp(name, "F") || !strcmp(name, "self.chassis.go_forward")) out.action = Action::Forward;
    else if (!strcmp(name, "B") || !strcmp(name, "self.chassis.go_back")) out.action = Action::Backward;
    else if (!strcmp(name, "L") || !strcmp(name, "self.chassis.turn_left")) out.action = Action::Left;
    else if (!strcmp(name, "R") || !strcmp(name, "self.chassis.turn_right")) out.action = Action::Right;
    else if (!strcmp(name, "S") || !strcmp(name, "self.chassis.stop")) out.action = Action::Stop;
    else return false;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    out.speed = default_speed;
    if (!*cursor) return true;
    if (out.action == Action::Stop) return false;
    errno = 0;
    char *end = nullptr;
    long speed = strtol(cursor, &end, 10);
    if (end == cursor || errno == ERANGE || speed < 0 || speed > 100) return false;
    while (isspace(static_cast<unsigned char>(*end))) ++end;
    if (*end) return false;
    out.speed = static_cast<int>(speed);
    return true;
}

inline void WheelSpeeds(Action action, int speed, int &left, int &right) {
    left = right = 0;
    switch (action) {
        case Action::Forward: left = speed; right = speed; break;
        case Action::Backward: left = -speed; right = -speed; break;
        case Action::Left: left = -speed; right = speed; break;
        case Action::Right: left = speed; right = -speed; break;
        case Action::Stop: break;
    }
}

// NOD / SHAKE / HEAD [C | pan tilt]。角度 0..180，90 为正前方。
inline bool ParseHead(char *line, HeadCommand &out) {
    char *cursor = line;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    char *name = cursor;
    while (*cursor && !isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    if (*cursor) *cursor++ = '\0';
    for (char *p = name; *p; ++p) *p = static_cast<char>(toupper(static_cast<unsigned char>(*p)));
    if (!strcmp(name, "NOD")) {
        out.kind = HeadKind::Nod;
        return true;
    }
    if (!strcmp(name, "SHAKE")) {
        out.kind = HeadKind::Shake;
        return true;
    }
    if (strcmp(name, "HEAD") && strcmp(name, "H")) return false;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    if (!*cursor || !strcmp(cursor, "C") || !strcmp(cursor, "c")) {
        out.kind = HeadKind::Set;
        out.pan = 90;
        out.tilt = 90;
        return true;
    }
    errno = 0;
    char *end = nullptr;
    long pan = strtol(cursor, &end, 10);
    if (end == cursor || errno == ERANGE || pan < 0 || pan > 180) return false;
    cursor = end;
    while (isspace(static_cast<unsigned char>(*cursor))) ++cursor;
    long tilt = strtol(cursor, &end, 10);
    if (end == cursor || errno == ERANGE || tilt < 0 || tilt > 180) return false;
    while (isspace(static_cast<unsigned char>(*end))) ++end;
    if (*end) return false;
    out.kind = HeadKind::Set;
    out.pan = static_cast<int>(pan);
    out.tilt = static_cast<int>(tilt);
    return true;
}
