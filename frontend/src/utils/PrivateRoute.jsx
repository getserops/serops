import React from 'react';
import { Navigate, Route } from 'react-router-dom';
import AuthService from '../services/auth.service';


const PrivateRoute = ({children}) => {
  // Check if the user is authenticated
  const user = AuthService.getUser();

  // If authenticated, render the Admin layout, else navigate to the login page
  return user ? <>{children}</> : <Navigate to="/login" />;
};

export default PrivateRoute;
