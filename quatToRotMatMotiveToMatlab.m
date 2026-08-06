function R_matlab = quatToRotMatMotiveToMatlab(q)
w = q(1);
x = q(2);
y = q(3);
z = q(4);

R = [
    1 - 2*(y^2 + z^2), 2*(x*y - w*z),     2*(x*z + w*y);
    2*(x*y + w*z),     1 - 2*(x^2 + z^2), 2*(y*z - w*x);
    2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x^2 + y^2)
    ];

R_matlab = [
    R(1,1), R(1,3), R(1,2);
    R(3,1), R(3,3), R(3,2);
    R(2,1), R(2,3), R(2,2)
    ];
end