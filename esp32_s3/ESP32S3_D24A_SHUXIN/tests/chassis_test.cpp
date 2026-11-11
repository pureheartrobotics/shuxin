#include "../main/main.cpp"

bool parse(const char *input,Command &cmd){
    char text[160];strcpy(text,input);return ParseCommand(text,70,cmd);
}
void expect(int a1,int a2,int b1,int b2,int c1,int c2,int d1,int d2){
    assert(levels[MOTOR_AIN1_GPIO]==a1 && levels[MOTOR_AIN2_GPIO]==a2);
    assert(levels[MOTOR_BIN1_GPIO]==b1 && levels[MOTOR_BIN2_GPIO]==b2);
    assert(levels[MOTOR_CIN1_GPIO]==c1 && levels[MOTOR_CIN2_GPIO]==c2);
    assert(levels[MOTOR_DIN1_GPIO]==d1 && levels[MOTOR_DIN2_GPIO]==d2);
}
int main(){
    Tb6612Chassis chassis;chassis.Initialize();
    assert(levels[MOTOR_STBY_GPIO]==0);
    Command command;
    assert(parse("F",command));chassis.Execute(command);expect(1,0,0,1,1,0,0,1);
    assert(duties[0]==716 && duties[1]==716 && duties[2]==716 && duties[3]==716);
    const int64_t before=fake_us;
    chassis.Execute(command);assert(fake_us==before); // heartbeat keeps PWM continuous
    assert(parse("B 30",command));chassis.Execute(command);expect(0,1,1,0,0,1,1,0);
    assert(parse("L 50",command));chassis.Execute(command);expect(0,1,0,1,0,1,0,1);
    assert(parse("R 50",command));chassis.Execute(command);expect(1,0,1,0,1,0,1,0);
    const int64_t started=fake_us;
    fake_us=started+MOTION_TIMEOUT_US-1;chassis.Poll();assert(!strcmp(chassis.State(),"moving"));
    fake_us++;chassis.Poll();expect(1,1,1,1,1,1,1,1);assert(duties[0]==1024);
    assert(!strcmp(chassis.State(),"braking"));
    fake_us+=BRAKE_DURATION_US-1;chassis.Poll();assert(levels[MOTOR_STBY_GPIO]==1);
    fake_us++;chassis.Poll();assert(levels[MOTOR_STBY_GPIO]==0);
    assert(parse("self.chassis.turn_left 20",command));chassis.Execute(command);expect(0,1,0,1,0,1,0,1);
    assert(parse("S",command));chassis.Execute(command);expect(1,1,1,1,1,1,1,1);
    assert(parse("F 20",command));chassis.Execute(command);fake_us+=BRAKE_DURATION_US;chassis.Poll();
    assert(!strcmp(chassis.State(),"moving"));expect(1,0,0,1,1,0,0,1);
    LineReader reader;const char *bad="F 101\n";
    for(const char *p=bad;*p;++p)reader.Feed(*p,Io::Uart1,chassis);
    fake_us+=MOTION_TIMEOUT_US;chassis.Poll();assert(!strcmp(chassis.State(),"braking"));
    assert(parse("F 0",command));chassis.Execute(command);fake_us+=BRAKE_DURATION_US;chassis.Poll();
    assert(levels[MOTOR_STBY_GPIO]==0);
    const char *invalid[]={"F -1","F 101","F 2x","F 1 2","F 999999999999999999999999999999","S 1","","X"};
    for(const char *input:invalid)assert(!parse(input,command));
    const char *names[]={"self.chassis.go_forward","self.chassis.go_back","self.chassis.turn_right","self.chassis.stop"};
    for(const char *input:names)assert(parse(input,command));
    HeadCommand head;
    char nod[]="NOD";assert(ParseHead(nod,head)&&head.kind==HeadKind::Nod);
    char shake[]="SHAKE";assert(ParseHead(shake,head)&&head.kind==HeadKind::Shake);
    char pose[]="HEAD 45 120";assert(ParseHead(pose,head)&&head.kind==HeadKind::Set&&head.pan==45&&head.tilt==120);
    char center[]="H C";assert(ParseHead(center,head)&&head.pan==90&&head.tilt==90);
    char bad_head[]="HEAD 200 90";assert(!ParseHead(bad_head,head));
    Neck neck;neck.Initialize();
    neck.Execute(head);
    assert(duties[4]>0 && duties[5]>0);
    for(int i=0;i<110;++i)reader.Feed('F',Io::Uart1,chassis);
    reader.Feed('\n',Io::Uart1,chassis);
    assert(!reader.discard && reader.length==0 && levels[MOTOR_STBY_GPIO]==0);
    const char *good="F 20\r\n";
    for(const char *p=good;*p;++p)reader.Feed(*p,Io::Uart1,chassis);
    expect(1,0,0,1,1,0,0,1);
    reader.Feed('F',Io::Uart1,chassis);reader.Feed('\0',Io::Uart1,chassis);reader.Feed('\n',Io::Uart1,chassis);
    assert(!reader.discard && reader.length==0);
    puts("PASS: four-wheel directions, PWM, heartbeat, stop/timeout brake, brake recovery and invalid commands");
}
