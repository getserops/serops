import axios from "axios";

import AuthService from "./auth.service";

const BACKEND_HOST = import.meta.env.VITE_BASE_URL + "/auth";

const ProfileService = {};

ProfileService.add = (data) => {
    return axios.post(BACKEND_HOST + "/profile", data, AuthService.authHeader());
};

ProfileService.update = (_id, data) => {
    return axios.post(BACKEND_HOST + "/profile", data, AuthService.authHeader());
};

ProfileService.getOne = (_id) => {
    return axios.get(BACKEND_HOST + "/profile", AuthService.authHeader());
};
ProfileService.generatePDF = (data) => {
    return axios.post(BACKEND_HOST + "profile/pdf/", data, AuthService.authHeader());
};

ProfileService.resetPassword = (data) => {
    return axios.post(BACKEND_HOST + "/password", data, AuthService.authHeader());
};


ProfileService.uploadAvatar = (data) => {
    const token = localStorage.getItem('token');
    return axios.put(`${BACKEND_HOST}/profile/upload-avatar/`, data, {
        headers: {
            Authorization: `Token ${token}`,
            'Content-Type': 'multipart/form-data',
        },
    });
};

ProfileService.removeAvatar = () => {
    return axios.delete(`${BACKEND_HOST}/profile/upload-avatar/`, AuthService.authHeader());
};

export default ProfileService;
