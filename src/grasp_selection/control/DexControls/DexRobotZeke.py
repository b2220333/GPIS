from tfx import transform, vector, rotation
from DexConstants import DexConstants
from DexSerial import DexSerialInterface
from DexNumericSolvers import DexNumericSolvers
from ZekeState import ZekeState
from Logger import Logger
from math import sqrt
from numpy import pi, arctan, cos, sin
from numpy.linalg import norm
from time import sleep
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt

class DexRobotZeke:
    '''
    Abstraction for a robot profile. Contains all information specific
    to the Zeke robot, including its physical dimensions, joints
    accepted poses, etc. 
    '''

    #For the two offsets below, actual angle = desired angle + OFFSET
    PHI = 0.3 #zeke arm rotation angle offset to make calculations easier.
    THETA = -0.16 #zeke wrist rotation 0 degree offset.
    
    RESET_STATES = {"GRIPPER_SAFE_RESET" : ZekeState([pi + PHI, 0.1, 0.02, None, 0.036, 0]),
                                "GRIPPER_RESET" : ZekeState([None, None, None, THETA + pi/2, None, None]),
                                 "ZEKE_RESET_SHUTTER_FREE" : ZekeState([None, 0.01, None, None, None, None]), 
                                "ZEKE_RESET" : ZekeState([None, None, 0.01, None, None, None]),
                                "ZEKE_RESET_CLEAR_TABLE" : ZekeState([1.5 * pi + PHI, None, None, None, None, None])}
    
    ZEKE_LOCAL_T = transform(
                                            vector(-DexConstants.ZEKE_ARM_ORIGIN_OFFSET, 0, 0),
                                            rotation.identity(), 
                                            parent=DexConstants.ZEKE_LOCAL_FRAME,
                                            frame=DexConstants.WORLD_FRAME)

    def __init__(self, comm = DexConstants.COMM, baudrate = DexConstants.BAUDRATE, timeout = DexConstants.SER_TIMEOUT):
        self._zeke= DexSerialInterface(ZekeState, comm, baudrate, timeout)      
        self._zeke.start()
        self._target_state = self.getState()
        Logger.clear(ZekeState.NAME)
    
    def reset(self, rot_speed = DexConstants.DEFAULT_ROT_SPEED, tra_speed = DexConstants.DEFAULT_TRA_SPEED):
        self.gotoState(DexRobotZeke.RESET_STATES["GRIPPER_SAFE_RESET"], rot_speed, tra_speed, "Reset Gripper Safe")
        self.gotoState(DexRobotZeke.RESET_STATES["GRIPPER_RESET"], rot_speed, tra_speed, "Gripper Reset")
        self.gotoState(DexRobotZeke.RESET_STATES["ZEKE_RESET_SHUTTER_FREE"], rot_speed, tra_speed, "Reset Shutter Free")
        self.gotoState(DexRobotZeke.RESET_STATES["ZEKE_RESET"], rot_speed, tra_speed, "Reset Complete")
            
    def reset_clear_table(self, rot_speed = DexConstants.DEFAULT_ROT_SPEED, tra_speed = DexConstants.DEFAULT_TRA_SPEED):
        self.reset(rot_speed, tra_speed)
        #self.gotoState(DexRobotZeke.RESET_STATES["ZEKE_RESET_CLEAR_TABLE"], rot_speed, tra_speed, "Reset Clear Table")
            
    def stop(self):
        self._zeke.stop()
        
    def getState(self):
        return self._zeke.getState()       
        
    def grip(self, tra_speed = DexConstants.DEFAULT_TRA_SPEED):
        state = self._target_state.copy()
        state.set_gripper_grip(ZekeState.MIN_STATE().gripper_grip)
        self.gotoState(state, DexConstants.DEFAULT_ROT_SPEED, tra_speed, "Gripping")
        
    def unGrip(self, tra_speed = DexConstants.DEFAULT_TRA_SPEED):
        state = self._target_state.copy()
        state.set_gripper_grip(ZekeState.MAX_STATE().gripper_grip)
        self.gotoState(state, DexConstants.DEFAULT_ROT_SPEED, tra_speed, "Ungripping")
                    
    @staticmethod
    def pose_to_state(target_pose, prev_state):
        '''
        Takes in a pose w/ respect to zeke and returns the state using IK
        '''
        if target_pose.frame is not DexConstants.ZEKE_LOCAL_FRAME:
            raise Exception("Given target_pose is not in ZEKE LOCAL frame")
                
        #calculate rotation about z axis
        x = target_pose.position.x
        y = target_pose.position.y
        theta = DexNumericSolvers.get_cartesian_angle(x, y)
        
        state = ZekeState()
        state.set_arm_rot(theta + DexRobotZeke.PHI)
        state.set_arm_elev(target_pose.position.z)
        state.set_arm_ext(norm([x, y]))
        state.set_gripper_rot(target_pose.rotation.tb_angles.pitch_rad + DexRobotZeke.THETA)
        state.set_gripper_grip(prev_state.gripper_grip)
        
        return state
        
    def gotoState(self, target_state, rot_speed = DexConstants.DEFAULT_ROT_SPEED, tra_speed = DexConstants.DEFAULT_TRA_SPEED, name = None):

        def _boundGripperRot(rot):
            if rot is None:
                return None
            if abs(rot - ZekeState.MAX_STATE().gripper_rot) <= 0.01:
                return ZekeState.MAX_STATE().gripper_rot
            if abs(rot - ZekeState.MIN_STATE().gripper_rot) <= 0.01:
                return ZekeState.MIN_STATE().gripper_rot
            if rot > ZekeState.MAX_STATE().gripper_rot:
                return ZekeState.MAX_STATE().gripper_rot
            if rot < ZekeState.MIN_STATE().gripper_rot:
                return ZekeState.MIN_STATE().gripper_rot
            return rot
                
        target_state.set_gripper_rot(_boundGripperRot(target_state.gripper_rot))
        self._zeke.gotoState(target_state, rot_speed, tra_speed, name)
                
        self._target_state = target_state.copy()

    def transform(self, target_pose, name, rot_speed = DexConstants.DEFAULT_ROT_SPEED, tra_speed = DexConstants.DEFAULT_TRA_SPEED):
        target_pose = DexRobotZeke.ZEKE_LOCAL_T * target_pose

        if abs(target_pose.rotation.tb_angles.roll_rad) >= 0.0001:
            raise Exception("Can't perform rotation about x-axis on Zeke's gripper")
            
        target_state = DexRobotZeke.pose_to_state(target_pose, self._target_state)
        
        self.gotoState(target_state, rot_speed, tra_speed, name)
        
    def transform_aim_extend_grip(self, target_pose, name, rot_speed = DexConstants.DEFAULT_ROT_SPEED, tra_speed = DexConstants.DEFAULT_TRA_SPEED):
        target_pose = DexRobotZeke.ZEKE_LOCAL_T * target_pose
        
        if abs(target_pose.rotation.tb_angles.roll_rad) >= 0.0001:
            raise Exception("Can't perform rotation about x-axis on Zeke's gripper: "  + str(target_pose.rotation.euler))
            
        target_state = DexRobotZeke.pose_to_state(target_pose, self._target_state)
        aim_state = target_state.copy().set_arm_ext(ZekeState.MIN_STATE().arm_ext)
        
        self.unGrip()
                
        self.gotoState(aim_state, rot_speed, tra_speed, name + "_aim")
        self.gotoState(target_state, rot_speed, tra_speed, name + "_grasp")

        while not self.is_action_complete():
            sleep(0.01)
            
        self.grip()
        
    def _state_FK(self, state):
        arm_angle = state.arm_rot - DexRobotZeke.PHI
        z = state.arm_elev
        r = state.arm_ext
        x = r * cos(arm_angle)
        y = r * sin(arm_angle)
        
        return (x, y, z)
        
    def maintainState(self, s):
        self._zeke.maintainState(s)
        
    def is_action_complete(self):
        return self._zeke.is_action_complete()
        
    def plot(self):
        hist = self._zeke.state_hist
        
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')

        x = []
        y = []
        z = []

        for state in hist:
            pos = self._state_FK(state)
            x.append(pos[0])
            y.append(pos[1])
            z.append(pos[2])
        
        ax.plot(x, y, z, c="g", marker="o")

        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')

        plt.show()